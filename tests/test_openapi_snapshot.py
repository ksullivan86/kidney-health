"""The OpenAPI document is honest, stable and checked in (design note 14 change 2; ``app/openapi_doc.py``, ``scripts/gen_openapi.py``,
``docs/api/openapi.json``, ``docs/api/README.md``).

Covered: the committed file is current (the check the script's ``--check`` runs); operation ids are unique and readable; there is no 422 for
request validation, and the 400 the document names is the body the app really sends; every error status carries the shared problem shape; the
three security schemes are there and each route has the one its dependencies and path give it (held against ``tests/test_auth_coverage.py``'s
list of public routes and ``security.BEARER_PATHS``); ``info.version`` and ``info.x-api-version``; every ``$ref`` resolves; the live
``/openapi.json`` stays off by default and, when on, serves the committed document; the script works from a shell with a hostile environment.
No network."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from conftest import TestClient, make_settings
from test_auth_coverage import PUBLIC
from app import openapi_doc, security
from app.api_version import API_VERSION
from app.main import APP_VERSION, create_app

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs" / "api" / "openapi.json"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def load_script():
    spec = importlib.util.spec_from_file_location("gen_openapi", ROOT / "scripts" / "gen_openapi.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen = load_script()


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def operations(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(method, path): op for path, item in doc["paths"].items() for method, op in item.items() if method in METHODS}


# --------------------------------------------------------------------------- #
# The file and its check
# --------------------------------------------------------------------------- #


def test_the_committed_document_is_current():
    problems = gen.check(SNAPSHOT)
    assert not problems, (
        "docs/api/openapi.json is stale (a route, a model or a status code changed). Run `python scripts/gen_openapi.py`, read the diff, "
        "commit the file, and raise API_VERSION (app/api_version.py) if the change is a breaking one:\n  " + "\n  ".join(problems)
    )


def test_the_file_is_written_the_way_the_script_says(committed):
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert text == json.dumps(committed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert text.endswith("}\n") and not text.endswith("\n\n")


def test_a_stale_file_is_reported_with_what_differs(tmp_path, capsys, monkeypatch):
    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    del doc["paths"]["/api/meta"]
    doc["paths"]["/api/log"]["get"]["operationId"] = "something_else"
    doc["components"]["schemas"]["Problem"]["title"] = "Changed"
    doc["info"]["version"] = "0.0.1"
    stale = tmp_path / "openapi.json"
    stale.write_text(gen.render(doc), encoding="utf-8")
    lines = gen.check(stale)
    assert "+ operation GET /api/meta (meta_info)" in lines
    assert "~ operation GET /api/log: id something_else -> log_get_day" in lines
    assert "~ components.schemas.Problem" in lines and "~ info" in lines
    monkeypatch.setattr(gen, "OUT", stale)
    assert gen.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "is stale" in err and "+ operation GET /api/meta" in err and "run: python scripts/gen_openapi.py" in err
    assert gen.main([]) == 0 and gen.main(["--check"]) == 0  # rewriting makes it current again
    assert stale.read_text(encoding="utf-8") == SNAPSHOT.read_text(encoding="utf-8")


def test_a_missing_file_is_stale(tmp_path):
    assert gen.check(tmp_path / "nope.json") == [f"{tmp_path / 'nope.json'} does not exist"]


def test_the_script_runs_from_any_directory_with_a_hostile_environment(tmp_path):
    """No server, no network, no settings of the caller's: a shell with half a proxy set-up in it still checks cleanly."""
    env = {**os.environ, "AUTH_MODE": "proxy", "INSTANCE_NAME": "", "ENABLE_API_DOCS": "true", "DATA_DIR": str(tmp_path / "never"),
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_openapi.py"), "--check"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (tmp_path / "never").exists()  # the document is made without starting the app: nothing is created


# --------------------------------------------------------------------------- #
# Operation ids
# --------------------------------------------------------------------------- #


def test_operation_ids_are_unique_and_readable(committed):
    ops = operations(committed)
    ids = [op["operationId"] for op in ops.values()]
    assert len(ops) > 150
    assert [i for i, n in Counter(ids).items() if n > 1] == []
    for i in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", i), i
        assert "_api_" not in i and not i.startswith("api_"), i  # not FastAPI's default, which spells out the path (login_api_auth_login_post)
    assert ops[("post", "/api/auth/login")]["operationId"] == "auth_login"
    assert ops[("post", "/api/log")]["operationId"] == "log_create_entry"
    assert ops[("get", "/api/meta")]["operationId"] == "meta_info"
    assert ops[("post", "/mcp")]["operationId"] == "mcp_post"
    assert ops[("post", "/push/v1/body")]["operationId"] == "push_body"
    assert ops[("get", "/api/guidance/next-meal")]["operationId"] != ops[("post", "/api/ai/next-meal")]["operationId"]


def test_the_live_document_has_the_same_ids(client):
    live = client.app.openapi()
    assert {k: v["operationId"] for k, v in operations(live).items()} == {k: v["operationId"] for k, v in operations(json.loads(SNAPSHOT.read_text())).items()}


def test_an_id_does_not_move_with_the_path_or_the_method():
    class Route:
        def __init__(self, name, tags, path="/api/x", methods=("GET",)):
            self.name, self.tags, self.path, self.methods = name, tags, path, methods

    assert openapi_doc.operation_id(Route("list_foods", ["foods"])) == "foods_list_foods"
    assert openapi_doc.operation_id(Route("list_foods", ["foods"], "/api/v2/things", ("POST",))) == "foods_list_foods"
    assert openapi_doc.operation_id(Route("foods_builtin", ["foods"])) == "foods_builtin"  # already starts with its tag
    assert openapi_doc.operation_id(Route("foods", ["foods"])) == "foods"
    assert openapi_doc.operation_id(Route("healthz", [])) == "healthz"
    assert openapi_doc.operation_id(Route("next meal", ["ai", "voice"])) == "ai_next_meal"  # the first tag; odd characters become _


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def test_no_422_for_validation_is_left(committed):
    refs = json.dumps(committed)
    assert "HTTPValidationError" not in refs and '"ValidationError"' not in refs
    assert "HTTPValidationError" not in committed["components"]["schemas"] and "ValidationError" not in committed["components"]["schemas"]
    with422 = [(m, p) for (m, p), op in operations(committed).items() if "422" in op["responses"]]
    assert with422 == [("get", "/api/profile/suggested-targets")]  # the one 422 a route really returns (out of scope), declared by the route
    assert committed["paths"]["/api/profile/suggested-targets"]["get"]["responses"]["422"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Problem"}


def test_every_operation_with_input_documents_the_400_the_app_sends(committed):
    for (method, path), op in operations(committed).items():
        takes_input = bool(op.get("parameters") or op.get("requestBody"))
        if takes_input:
            bad = op["responses"].get("400")
            assert bad is not None, (method, path)
            if "$ref" in bad:
                assert bad == {"$ref": "#/components/responses/BadRequest"}, (method, path)
            else:  # the route words its own 400 (barcode lookups); the body is still the validation one
                assert bad["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ValidationProblem"}, (method, path)
    bad = committed["components"]["responses"]["BadRequest"]
    assert bad["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ValidationProblem"}
    schema = committed["components"]["schemas"]["ValidationProblem"]
    assert set(schema["properties"]) == {"detail", "errors"} and schema["required"] == ["detail"]
    assert set(schema["properties"]["errors"]["items"]["required"]) == {"type", "loc", "msg"}


def test_the_400_in_the_document_is_the_one_the_app_sends(client):
    r = client.post("/api/log", json={"servings": "lots"})
    assert r.status_code == 400
    body = r.json()
    assert set(body) == {"detail", "errors"} and isinstance(body["detail"], str)
    assert body["errors"] and all(set(e) == {"type", "loc", "msg"} for e in body["errors"])
    assert all(isinstance(part, (str, int)) for e in body["errors"] for part in e["loc"])
    assert "input" not in json.dumps(body)


def test_the_other_documented_errors_have_the_documented_shape(two_clients):
    admin, sam = two_clients
    anon = TestClient(admin.app, base_url=str(admin.base_url))
    cases = [
        (anon.get("/api/log"), 401),
        (sam.get("/api/admin/users"), 403),
        (sam.request("POST", "/api/log", json={}, headers={"X-Requested-With": ""}), 403),  # no CSRF header
        (sam.delete("/api/log/999999"), 404),
        (sam.post("/api/log", content=b"x" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"}), 413),
        (anon.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password-1234"}), 401),
    ]
    for response, status in cases:
        assert response.status_code == status, (status, response.text[:200])
        body = response.json()
        assert isinstance(body["detail"], str), body


def test_every_error_status_points_at_a_shared_component_or_carries_the_problem_shape(committed):
    problem = {"$ref": "#/components/schemas/Problem"}
    declared = 0
    for (method, path), op in operations(committed).items():
        for status, response in op["responses"].items():
            if status in ("default",) or (status.isdigit() and int(status) >= 400):
                if "$ref" in response:
                    assert response["$ref"].startswith("#/components/responses/"), (method, path, status)
                else:
                    declared += 1  # a route's own words (barcode, suggested targets, the 412 of a log entry) with the shared shape added
                    schema = response["content"]["application/json"]["schema"]
                    assert schema in (problem, {"$ref": "#/components/schemas/ValidationProblem"}, {"$ref": "#/components/schemas/EntryConflictProblem"},
                                      {"$ref": "#/components/schemas/JsonRpcError"}), (method, path, status)
    assert declared >= 7
    responses = committed["components"]["responses"]
    assert {"BadRequest", "Unauthorized", "BearerUnauthorized", "Forbidden", "NotFound", "Conflict", "PayloadTooLarge",
            "UnsupportedMediaType", "TooManyRequests", "MethodNotAllowed", "Error"} <= set(responses)
    assert "Retry-After" in responses["TooManyRequests"]["headers"]
    assert "WWW-Authenticate" in responses["BearerUnauthorized"]["headers"]
    assert committed["components"]["schemas"]["Problem"]["required"] == ["detail"]
    assert committed["components"]["schemas"]["EntryConflictProblem"]["required"] == ["detail", "current"]


def test_every_api_operation_has_the_default_error(committed):
    for (method, path), op in operations(committed).items():
        if path.startswith("/api/"):
            assert op["responses"]["default"] == {"$ref": "#/components/responses/Error"}, (method, path)


def test_the_structural_statuses_are_where_the_app_is_built_to_answer_them(committed):
    ops = operations(committed)
    for (method, path), op in ops.items():
        if not path.startswith("/api/"):
            continue
        codes = set(op["responses"])
        if (method, path) not in PUBLIC:
            assert {"401", "403"} <= codes, (method, path)
        if method in ("post", "put", "patch"):
            assert {"403", "413"} <= codes, (method, path)
        if "{" in path or path.startswith(("/api/ai/", "/api/vision/")):
            assert "404" in codes, (method, path)
    for table in (openapi_doc.CONFLICT, openapi_doc.UNSUPPORTED_MEDIA, openapi_doc.RATE_LIMITED, openapi_doc.UNAUTHORIZED_PUBLIC):
        assert set(table) <= {op["operationId"] for op in ops.values()}, set(table) - {op["operationId"] for op in ops.values()}
    by_id = {op["operationId"]: op for op in ops.values()}
    assert all("409" in by_id[i]["responses"] for i in openapi_doc.CONFLICT)
    assert all("415" in by_id[i]["responses"] for i in openapi_doc.UNSUPPORTED_MEDIA)
    assert all("429" in by_id[i]["responses"] for i in openapi_doc.RATE_LIMITED)
    assert set(by_id["log_update_entry"]["responses"]) >= {"412"} and set(by_id["log_delete_entry"]["responses"]) >= {"412"}


def test_the_405_stubs_say_405(committed):
    stubs = [(k, op) for k, op in operations(committed).items() if op["operationId"].endswith("_not_allowed")]
    assert len(stubs) == 8
    for (method, path), op in stubs:
        assert path in ("/mcp", "/push/v1/body") and method != "post"
        assert "200" not in op["responses"] and op["responses"]["405"] == {"$ref": "#/components/responses/MethodNotAllowed"}
        assert "security" not in op


def test_the_bearer_routes_answer_what_the_document_says(client):
    assert client.post("/mcp", json={}).status_code == 404  # assistant access is off: the document's 404
    assert client.get("/mcp").status_code == 404
    assert client.patch("/api/admin/settings", json={"assistant.enabled": True, "push.enabled": True}).status_code == 200
    r = client.get("/mcp")
    assert r.status_code == 405 and r.headers["allow"] == "POST" and r.json() == {"detail": "Method Not Allowed"}
    assert client.get("/push/v1/body").status_code == 405
    r = client.post("/mcp", json={})
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer") and isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- #
# Security schemes
# --------------------------------------------------------------------------- #


def test_the_security_schemes_are_present(committed):
    schemes = committed["components"]["securitySchemes"]
    assert set(schemes) == {"session", "assistantToken", "deviceToken"}
    session = schemes["session"]
    assert (session["type"], session["in"], session["name"]) == ("apiKey", "cookie", "kh_session")
    for text in ("__Host-kh_session", "kh_session", "X-Requested-With: kidney-health", "POST, PUT, PATCH, DELETE", "403"):
        assert text in session["description"], text
    for name, prefix, route in (("assistantToken", "kha_", "/mcp"), ("deviceToken", "khd_", "/push/v1/body")):
        scheme = schemes[name]
        assert (scheme["type"], scheme["scheme"]) == ("http", "bearer") and prefix in scheme["bearerFormat"]
        assert prefix in scheme["description"] and route in scheme["description"]


def test_the_scheme_names_and_values_are_the_apps(client):
    from app.auth import sessions
    from app.auth.api_tokens import DEVICE_PREFIX, PREFIX

    assert sessions.COOKIE_HTTP == "kh_session" and sessions.COOKIE_HTTPS == "__Host-kh_session"
    assert (PREFIX, DEVICE_PREFIX) == ("kha_", "khd_")
    assert security.CSRF_HEADER == "X-Requested-With" and security.CSRF_HEADER_VALUE == "kidney-health"


def test_each_route_has_the_scheme_its_dependencies_give_it(committed, client):
    ops = operations(committed)
    seen = Counter()
    for (method, path), op in ops.items():
        scheme = op.get("security")
        if path.startswith("/api/"):
            if (method, path) in PUBLIC:
                assert scheme is None, (method, path)  # the public auth routes: no sign-in
            else:
                assert scheme == [{"session": []}], (method, path)
        elif (method, path) == ("post", "/mcp"):
            assert scheme == [{"assistantToken": []}]
        elif (method, path) == ("post", "/push/v1/body"):
            assert scheme == [{"deviceToken": []}]
        else:
            assert scheme is None, (method, path)  # /healthz, /sw.js and the 405 stubs
        seen[json.dumps(scheme)] += 1
    assert seen[json.dumps([{"session": []}])] > 100 and seen[json.dumps([{"assistantToken": []}])] == 1 and seen[json.dumps([{"deviceToken": []}])] == 1


def test_the_public_list_is_what_an_anonymous_caller_gets_through(committed, anon_client):
    """The document's 'no security' routes are exactly the ones that answer an anonymous caller without a 401."""
    for (method, path), op in operations(committed).items():
        if not path.startswith("/api/") or "security" in op:
            continue
        assert (method, path) in PUBLIC
        r = anon_client.request(method.upper(), path, json={})
        assert r.status_code != 401 or (method, path) == ("post", "/api/auth/login"), (method, path, r.status_code)


def test_the_bearer_paths_are_the_apps(committed):
    assert {p for (_, p) in openapi_doc.BEARER_OPERATIONS} == set(security.BEARER_PATHS)
    assert set(openapi_doc.BEARER_OPERATIONS.values()) == {"assistantToken", "deviceToken"}
    unsafe_outside_api = {(m, p) for (m, p), op in operations(committed).items() if not p.startswith("/api/") and m in ("post", "put", "patch", "delete")}
    assert {p for _, p in unsafe_outside_api} == set(security.BEARER_PATHS)


# --------------------------------------------------------------------------- #
# Versions and links
# --------------------------------------------------------------------------- #


def test_the_versions(committed):
    assert committed["info"]["version"] == APP_VERSION
    assert committed["info"]["x-api-version"] == API_VERSION == 1 and isinstance(API_VERSION, int)
    assert committed["openapi"].startswith("3.1")
    assert "x-api-version" in committed["info"]["description"]


def test_every_reference_resolves_and_every_shared_response_is_used(committed):
    text = json.dumps(committed)
    for ref in set(re.findall(r'"\$ref": "#/([^"]+)"', text)):
        node: Any = committed
        for part in ref.split("/"):
            assert part in node, ref
            node = node[part]
    for name in committed["components"]["responses"]:
        assert f'"#/components/responses/{name}"' in text, f"components.responses.{name} is not used by any operation"
    for name in committed["components"]["schemas"]:
        assert f'"#/components/schemas/{name}"' in text, f"components.schemas.{name} is not used by anything"


# --------------------------------------------------------------------------- #
# The live document
# --------------------------------------------------------------------------- #


def test_the_live_document_stays_off_by_default(client):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_the_snapshot_needs_neither_the_docs_flag_nor_a_server(tmp_path, foods_json, committed):
    assert json.loads(json.dumps(create_app(make_settings(tmp_path / "a", foods_json)).openapi())) == committed
    on = create_app(make_settings(tmp_path / "b", foods_json, docs_enabled=True))
    with TestClient(on) as c:
        served = c.get("/openapi.json")
        assert served.status_code == 200 and served.json() == committed  # the live document is the checked-in one
        assert c.get("/docs").status_code == 200


def test_building_the_document_changes_nothing_on_disk(tmp_path, foods_json):
    settings = make_settings(tmp_path / "data-dir", foods_json)
    create_app(settings).openapi()
    assert not (tmp_path / "data-dir").exists()
