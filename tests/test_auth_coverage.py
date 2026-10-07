"""Behavioural auth coverage (note 07 §4.10, §9 N5 (8)): every ``/api`` route answers 401 to an
anonymous request, except the short public list, including routes hidden from the OpenAPI schema.

FastAPI >= 0.137 keeps included routers as a tree, so ``app.routes`` alone finds no ``APIRoute``;
the routes are collected from ``app.openapi()`` **and** from a walk of the route tree (which also
sees ``include_in_schema=False`` routes), and then exercised with real requests.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import pytest

from conftest import TestClient

PUBLIC = {
    ("get", "/api/auth/status"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/setup"),
    ("post", "/api/auth/register"),
    ("post", "/api/auth/reset"),
    ("post", "/api/auth/reset/info"),
}
METHODS = ("get", "post", "put", "patch", "delete")


def _walk(routes: Iterable[Any], prefix: str = "") -> Iterable[tuple[str, str, bool]]:
    """``(method, path, include_in_schema)`` for every endpoint in a (possibly nested) route list."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):  # FastAPI >= 0.137: an included router
            for ctx in contexts():
                for method in getattr(ctx, "methods", None) or ():
                    yield method.lower(), ctx.path, bool(getattr(ctx, "include_in_schema", True))
            continue
        original = getattr(route, "original_router", None)
        if original is not None:  # fallback if the context API changes again
            include = getattr(route, "include_context", None)
            yield from _walk(original.routes, prefix + (getattr(include, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            for method in methods:
                yield method.lower(), prefix + path, bool(getattr(route, "include_in_schema", True))
        sub = getattr(route, "routes", None)
        if sub and not methods:
            yield from _walk(sub, prefix + (path or ""))


def api_operations(app: Any) -> set[tuple[str, str]]:
    ops = {
        (method, path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if path.startswith("/api/") and method in METHODS
    }
    ops |= {(m, p) for m, p, _ in _walk(app.routes) if p.startswith("/api/") and m in METHODS}
    return ops


def test_the_route_walk_finds_the_api(anon_client):
    walked = {(m, p) for m, p, _ in _walk(anon_client.app.routes)}
    for op in (("get", "/api/foods"), ("post", "/api/auth/login"), ("delete", "/api/me"), ("get", "/api/admin/audit")):
        assert op in walked, op
    assert len(api_operations(anon_client.app)) > 60


def test_every_api_route_requires_auth(anon_client):
    ops = api_operations(anon_client.app)
    assert PUBLIC <= ops
    checked = 0
    for method, path in sorted(ops):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = anon_client.request(method.upper(), url, json={})
        assert r.status_code == 401, (method, path, r.status_code, r.text[:200])
        checked += 1
    assert checked > 50


# Every route the v0.3 contract adds (ARCHITECTURE.md "M2 API: targets and labs", "guidance", "barcode",
# "AI and photos", "M3: the handbook at /learn"). The walk above finds routes generically; this list also
# fails when one of them is missing or renamed, so the contract and the app cannot drift apart unnoticed.
V03_ROUTES = {
    ("get", "/api/profile/suggested-targets"),
    ("post", "/api/labs"), ("get", "/api/labs"), ("delete", "/api/labs/{lab_id}"), ("get", "/api/labs/kidney-function"),
    ("get", "/api/guidance/next-meal"), ("get", "/api/guidance/swaps"), ("get", "/api/guidance/hypo-options"),
    ("post", "/api/guidance/plan-day"), ("get", "/api/guidance/insights/day"), ("get", "/api/guidance/insights/period"),
    ("get", "/api/guidance/rules"), ("get", "/api/guidance/not-for-me"), ("put", "/api/guidance/not-for-me/{food_id}"),
    ("delete", "/api/guidance/not-for-me/{food_id}"),
    ("post", "/api/log/batch"),
    ("post", "/api/foods/barcode"),
    ("get", "/api/ai/status"), ("post", "/api/ai/next-meal"), ("post", "/api/ai/parse-meal"), ("post", "/api/ai/consent"),
    ("delete", "/api/ai/consent/{provider_id}"), ("get", "/api/ai/audit"), ("delete", "/api/ai/audit"),
    ("post", "/api/vision/label"), ("post", "/api/vision/plate"),
    ("get", "/api/me/ai"), ("patch", "/api/me/ai"), ("put", "/api/me/ai/provider"), ("delete", "/api/me/ai/provider"),
    ("post", "/api/me/ai/probe"),
    ("get", "/api/admin/ai-providers"), ("post", "/api/admin/ai-providers"), ("put", "/api/admin/ai-providers/{provider_id}"),
    ("delete", "/api/admin/ai-providers/{provider_id}"), ("post", "/api/admin/ai-providers/{provider_id}/probe"),
    ("get", "/api/admin/ai-usage"),
    ("get", "/api/handbook"),
}


def test_every_v03_route_exists_and_needs_a_session(anon_client):
    ops = api_operations(anon_client.app)
    assert V03_ROUTES <= ops, sorted(V03_ROUTES - ops)
    assert not V03_ROUTES & PUBLIC
    for method, path in sorted(V03_ROUTES):
        r = anon_client.request(method.upper(), re.sub(r"\{[^}]+\}", "1", path), json={})
        assert r.status_code == 401 and r.json()["detail"] == "Sign in required", (method, path, r.status_code)


def test_public_routes_answer_without_a_session(anon_client):
    assert anon_client.get("/api/auth/status").status_code == 200
    assert anon_client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401
    assert anon_client.post("/api/auth/setup", json={"code": "AAAA-AAAA-AAAA-AAAA"}).status_code == 409  # done already
    assert anon_client.post("/api/auth/register", json={"username": "x", "password": "y"}).status_code == 403
    assert anon_client.post("/api/auth/reset", json={"token": "a.b", "password": "y"}).status_code == 400
    assert anon_client.post("/api/auth/reset/info", json={"token": "a.b"}).status_code == 400


def test_invalid_bodies_still_get_401_not_400(anon_client):
    """Dependencies run before body validation, so an anonymous caller learns nothing about the shape."""
    assert anon_client.post("/api/log", json={"nonsense": True}).status_code == 401
    assert anon_client.put("/api/me/keys/usda", json={"api_key": " has spaces "}).status_code == 401
    assert anon_client.patch("/api/admin/users/1", json={"role": "god"}).status_code == 401


def test_admin_routes_are_403_for_people_who_are_not_admins(two_clients):
    admin, sam = two_clients
    for method, path in sorted(api_operations(admin.app)):
        if not path.startswith("/api/admin/"):
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = sam.request(method.upper(), url, json={})
        assert r.status_code == 403, (method, path, r.status_code)


def test_no_api_route_hides_from_the_schema():
    """§9 N5 (8): ``include_in_schema=False`` must not be used for /api routes (the walk above would
    still catch one, but keep the schema complete for reviewers)."""
    root = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"@\w+\.(get|post|put|patch|delete|api_route)\(([^)]*)include_in_schema\s*=\s*False", text):
            offenders.append(f"{path.relative_to(root)}: {match.group(0)[:80]}")
    routers_hidden = [
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if re.search(r"APIRouter\([^)]*prefix=\"/api[^)]*include_in_schema\s*=\s*False", p.read_text(encoding="utf-8"))
    ]
    assert not offenders and not routers_hidden, offenders + routers_hidden


@pytest.mark.parametrize("path", ["/healthz", "/sw.js", "/manifest.webmanifest", "/"])
def test_non_api_public_paths_do_not_need_a_session(anon_client, path):
    assert anon_client.get(path).status_code in (200, 404)  # 404 only when the frontend file is absent


def test_setup_gate_answers_503_until_first_run_setup(tmp_path, foods_json):
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path / "d", foods_json=foods_json))) as c:
        status = c.get("/api/auth/status").json()
        assert status["setup_required"] is True and status["user"] is None
        for method, path in (("get", "/api/foods"), ("get", "/api/profile"), ("post", "/api/log"), ("get", "/api/me")):
            r = c.request(method.upper(), path, json={})
            assert r.status_code == 503 and r.json() == {"detail": "Setup required", "setup_required": True}, path
        assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 503
