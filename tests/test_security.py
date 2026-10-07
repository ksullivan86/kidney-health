"""Security middleware (note 01 §5.5, §10 S1-S4; note 07 §4.8, §9 N4, N10): headers, CSP, Host
allowlist, trusted proxies, CSRF, body limits, docs, error and log redaction."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, SecretStr, field_validator

from app import security
from app.config import Settings, normalize
from app.main import create_app

from conftest import BASE_URL, DAY, TestClient, find_food

SPEC_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "img-src 'self' blob:; connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; "
    "media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "require-trusted-types-for 'script'; trusted-types kh-sw"
)
EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-frame-options": "DENY",
}
STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


def assert_security_headers(response: Any, *, https: bool = False) -> None:
    csp = response.headers.get("content-security-policy")
    assert csp == (SPEC_CSP + "; upgrade-insecure-requests" if https else SPEC_CSP), csp
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, name
    if https:
        assert response.headers.get("strict-transport-security") == "max-age=31536000"
    else:
        assert "strict-transport-security" not in response.headers


class SecretBody(BaseModel):
    password: SecretStr
    api_key: SecretStr | None = None
    note: str = ""

    @field_validator("password")
    @classmethod
    def long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 15:
            raise ValueError(f"too short: {value.get_secret_value()}")  # a careless message must not leak
        return value


def make_echo_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    """A minimal app with only the security stack, echoing what the middleware produced."""
    settings = normalize(Settings(data_dir=tmp_path / "data", **overrides))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(RequestValidationError, security.validation_error_handler)
    security.install(app, settings)

    @app.api_route("/api/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def echo(request: Request) -> dict[str, Any]:
        body = await request.body()
        return {
            "peer": request.state.peer,
            "client_ip": request.state.client_ip,
            "scheme": request.state.scheme,
            "proxy_trusted": request.state.proxy_trusted,
            "secure": security.request_is_secure(request.scope),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "size": len(body),
        }

    @app.post("/api/secret")
    def secret(body: SecretBody) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/page")
    def page() -> PlainTextResponse:
        return PlainTextResponse("hello")

    @app.post("/form")
    def form() -> PlainTextResponse:
        return PlainTextResponse("posted")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    return app


# --------------------------------------------------------------------------- #
# Headers and CSP
# --------------------------------------------------------------------------- #


def test_headers_on_static_api_404_and_400(client):
    for response in (
        client.get("/"),
        client.get("/api/profile"),
        client.get("/api/foods/999999"),
        client.get("/no-such-file.txt"),
        client.post("/api/log", json={"date": DAY, "meal": "brunch", "food_id": 1}),
        client.get("/healthz"),
    ):
        assert_security_headers(response)
    assert client.get("/api/foods/999999").status_code == 404
    assert client.get("/no-such-file.txt").status_code == 404
    assert client.post("/api/log", json={"date": DAY, "meal": "brunch", "food_id": 1}).status_code == 400


def test_csp_tokens_are_strict():
    tokens = {t for directive in security.CONTENT_SECURITY_POLICY.split(";") for t in directive.split()}
    assert "'unsafe-inline'" not in tokens and "'unsafe-eval'" not in tokens
    assert "'wasm-unsafe-eval'" in tokens  # the barcode decoder is WebAssembly (note 03)
    directives = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in security.CONTENT_SECURITY_POLICY.split(";")) if d}
    assert directives["trusted-types"] == ["kh-sw"]
    assert directives["require-trusted-types-for"] == ["'script'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["script-src"] == ["'self'", "'wasm-unsafe-eval'"]
    assert "upgrade-insecure-requests" not in directives
    assert security.CONTENT_SECURITY_POLICY == SPEC_CSP


def test_cache_control_no_store_only_on_api(client):
    assert client.get("/api/profile").headers["cache-control"] == "no-store"
    assert client.get("/api/foods/999999").headers["cache-control"] == "no-store"
    assert client.get("/").headers.get("cache-control") != "no-store"


def test_hsts_and_upgrade_only_over_https_from_a_trusted_proxy(tmp_path):
    app = make_echo_app(tmp_path)
    with TestClient(app, client=("127.0.0.1", 40000)) as trusted:
        r = trusted.get("/page", headers={"X-Forwarded-Proto": "https"})
        assert_security_headers(r, https=True)
        r = trusted.get("/api/echo", headers={"X-Forwarded-Proto": "https"})
        assert r.json()["scheme"] == "https" and r.json()["secure"] is True
        assert_security_headers(trusted.get("/page"))  # plain http from the same peer
    with TestClient(app, client=("203.0.113.9", 40000)) as untrusted:
        r = untrusted.get("/page", headers={"X-Forwarded-Proto": "https"})
        assert_security_headers(r)
        assert untrusted.get("/api/echo", headers={"X-Forwarded-Proto": "https"}).json()["scheme"] == "http"


def test_hsts_can_be_disabled(tmp_path):
    with TestClient(make_echo_app(tmp_path, hsts_max_age=0), client=("127.0.0.1", 1)) as c:
        r = c.get("/page", headers={"X-Forwarded-Proto": "https"})
        assert "strict-transport-security" not in r.headers
        assert r.headers["content-security-policy"].endswith("; upgrade-insecure-requests")


def test_unhandled_error_still_carries_headers(tmp_path):
    with TestClient(make_echo_app(tmp_path), raise_server_exceptions=False) as c:
        r = c.get("/boom")
        assert r.status_code == 500 and r.text == "Internal Server Error"
        assert_security_headers(r)
        assert "kaboom" not in r.text


def test_no_cors_preflight_answers(client):
    r = client.options("/api/log", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert not any(h.lower().startswith("access-control-allow") for h in r.headers)


def test_static_files_have_no_html_sinks():
    """Note 01 §5.5: DOM APIs and textContent only (CSP + Trusted Types)."""
    pattern = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b")
    offenders = []
    for path in STATIC_DIR.rglob("*.js"):
        if "vendor" in path.relative_to(STATIC_DIR).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(STATIC_DIR)}:{number}")
    assert offenders == []


def test_static_html_has_no_inline_script():
    index = STATIC_DIR / "index.html"
    html = index.read_text(encoding="utf-8")
    inline = [m.group(0)[:60] for m in re.finditer(r"<script\b(?![^>]*\bsrc=)[^>]*>", html, re.I)]
    # the JSON data island of the preview build is not executable script; anything else is
    inline = [tag for tag in inline if "application/json" not in tag]
    assert inline == []


# --------------------------------------------------------------------------- #
# Host allowlist (DNS rebinding, S1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["/", "/api/profile", "/sw.js", "/healthz"])
def test_unknown_host_is_refused(client, path):
    r = client.get(path, headers={"Host": "evil.example"})
    assert r.status_code == 400 and r.json() == {"detail": "Unknown host"}
    assert_security_headers(r)


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8000", "127.0.0.1:8000", "192.168.1.10:8000", "10.244.1.17:8000", "[::1]:8000", "[fe80::1]", "LOCALHOST."],
)
def test_ip_literals_and_localhost_pass(client, host):
    assert client.get("/healthz", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["", "evil.example:8000", "::1", "[::1", "localhost:abc", "kidney.example.org.evil.example", "0x7f.1"])
def test_malformed_or_unlisted_hosts_fail(client, host):
    assert client.get("/healthz", headers={"Host": host}).status_code == 400


def test_allowed_hosts_and_public_url(tmp_path):
    app = make_echo_app(tmp_path, allowed_hosts=("kidney.home.example", "*.lan.example"), public_url="https://kidney.example.org")
    with TestClient(app) as c:
        for host in ("kidney.home.example", "a.lan.example", "b.a.lan.example", "kidney.example.org", "kidney.example.org:443"):
            assert c.get("/page", headers={"Host": host}).status_code == 200, host
        for host in ("lan.example", "home.example", "example.org", "evil.example"):
            assert c.get("/page", headers={"Host": host}).status_code == 400, host


def test_unknown_host_is_logged_once(tmp_path, caplog):
    with TestClient(make_echo_app(tmp_path)) as c, caplog.at_level(logging.WARNING, logger="kidney_health.security"):
        for _ in range(3):
            c.get("/page", headers={"Host": "rebind.example"})
        assert c.app.state.security.snapshot()["rejected_hosts"] == 3
    lines = [r.getMessage() for r in caplog.records if "rebind.example" in r.getMessage()]
    assert len(lines) == 1 and "ALLOWED_HOSTS" in lines[0]


# --------------------------------------------------------------------------- #
# Trusted proxies (S2)
# --------------------------------------------------------------------------- #


def test_forwarded_for_ignored_from_untrusted_peer(tmp_path):
    app = make_echo_app(tmp_path)
    with TestClient(app, client=("198.51.100.7", 1234)) as c:
        data = c.get("/api/echo", headers={"X-Forwarded-For": "1.2.3.4"}).json()
        assert data["client_ip"] == "198.51.100.7" and data["peer"] == "198.51.100.7"
        assert data["proxy_trusted"] is False
        assert "x-forwarded-for" not in data["headers"]
    with TestClient(app, client=("127.0.0.1", 1234)) as c:
        data = c.get("/api/echo", headers={"X-Forwarded-For": "1.2.3.4"}).json()
        assert data["client_ip"] == "1.2.3.4" and data["peer"] == "127.0.0.1" and data["proxy_trusted"] is True
        assert data["secure"] is False  # a remote client over plain http, even via a loopback proxy
        # the right-most untrusted entry wins; a client cannot prepend its own
        data = c.get("/api/echo", headers={"X-Forwarded-For": "6.6.6.6, 1.2.3.4"}).json()
        assert data["client_ip"] == "1.2.3.4"
    assert app.state.security.snapshot()["first_forwarded_peer"] == "127.0.0.1"


def test_ipv4_mapped_peers_are_unmapped(tmp_path):
    """On a dual-stack socket an IPv4 proxy appears as ::ffff:a.b.c.d; it must still match 127.0.0.1."""
    app = make_echo_app(tmp_path)
    with TestClient(app, client=("::ffff:127.0.0.1", 1)) as c:
        data = c.get("/api/echo", headers={"X-Forwarded-For": "192.0.2.8"}).json()
        assert data["peer"] == "127.0.0.1" and data["client_ip"] == "192.0.2.8" and data["proxy_trusted"] is True


def test_trusted_proxies_cidr(tmp_path):
    app = make_echo_app(tmp_path, trusted_proxies=("10.88.0.0/16",))
    with TestClient(app, client=("10.88.3.4", 1)) as c:
        assert c.get("/api/echo", headers={"X-Forwarded-For": "192.0.2.5"}).json()["client_ip"] == "192.0.2.5"
    with TestClient(app, client=("127.0.0.1", 1)) as c:  # loopback no longer trusted
        assert c.get("/api/echo", headers={"X-Forwarded-For": "192.0.2.5"}).json()["client_ip"] == "127.0.0.1"


def test_identity_header_only_from_trusted_peer(tmp_path):
    app = make_echo_app(tmp_path, trusted_proxy_user_header="Remote-User", trusted_proxy_name_header="Remote-Name")
    with TestClient(app, client=("192.0.2.50", 1)) as c:
        data = c.get("/api/echo", headers={"Remote-User": "admin", "Remote-Name": "Mallory"}).json()
        assert "remote-user" not in data["headers"] and "remote-name" not in data["headers"]
    assert app.state.security.snapshot()["ignored_identity_headers"] == 1
    with TestClient(app, client=("::1", 1)) as c:
        data = c.get("/api/echo", headers={"Remote-User": "alice"}).json()
        assert data["headers"]["remote-user"] == "alice"


def test_proxy_secret_required_when_configured(tmp_path):
    secret = "s" * 40
    app = make_echo_app(tmp_path, trusted_proxy_user_header="Remote-User", trusted_proxy_secret=secret)
    with TestClient(app, client=("127.0.0.1", 1)) as c:
        # correct peer, wrong (or no) secret: forwarded and identity headers ignored
        for headers in ({}, {"X-Proxy-Secret": "wrong"}):
            data = c.get("/api/echo", headers={"Remote-User": "admin", "X-Forwarded-For": "1.2.3.4", **headers}).json()
            assert "remote-user" not in data["headers"] and data["client_ip"] == "127.0.0.1"
            assert "x-proxy-secret" not in data["headers"]
        # correct peer and secret: honoured, and the secret never reaches the app
        data = c.get("/api/echo", headers={"Remote-User": "alice", "X-Forwarded-For": "1.2.3.4", "X-Proxy-Secret": secret}).json()
        assert data["headers"]["remote-user"] == "alice" and data["client_ip"] == "1.2.3.4"
        assert "x-proxy-secret" not in data["headers"]
    with TestClient(app, client=("192.0.2.1", 1)) as c:  # right secret, untrusted peer: ignored
        data = c.get("/api/echo", headers={"Remote-User": "alice", "X-Proxy-Secret": secret}).json()
        assert "remote-user" not in data["headers"] and data["proxy_trusted"] is False


# --------------------------------------------------------------------------- #
# CSRF (note 07 §4.8, N10, S4)
# --------------------------------------------------------------------------- #


def test_cross_site_and_same_site_writes_are_refused(client):
    banana = find_food(client, "banana")
    body = {"date": DAY, "meal": "lunch", "food_id": banana["id"]}
    for site in ("cross-site", "same-site", "none"):
        r = client.post("/api/log", json=body, headers={"Sec-Fetch-Site": site})
        assert r.status_code == 403 and r.json() == {"detail": "Cross-site request refused"}, site
        assert_security_headers(r)
    r = client.post("/api/log", json=body, headers={"Sec-Fetch-Site": "same-origin", "Origin": BASE_URL})
    assert r.status_code == 201
    assert len(client.get("/api/log", params={"date": DAY}).json()["entries"]) == 1


def test_cross_site_reads_of_the_api_are_refused(client):
    for site in ("cross-site", "same-site"):
        assert client.get("/api/profile", headers={"Sec-Fetch-Site": site}).status_code == 403
    assert client.get("/api/profile", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.get("/api/profile", headers={"Sec-Fetch-Site": "none"}).status_code == 200  # typed URL / bookmark
    # top-level navigation to the app from another site still works
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code in (200, 404)


def test_x_requested_with_is_required_for_unsafe_api_requests(settings):
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME

    with TestClient(create_app(settings), headers={}) as bare:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        r = bare.post("/api/auth/login", json=login)  # login CSRF: the sign-in form needs the header too
        assert r.status_code == 403 and r.json() == {"detail": "Missing X-Requested-With header"}
        assert bare.post("/api/auth/login", json=login, headers={"X-Requested-With": "kidney-health"}).status_code == 200
        r = bare.post("/api/foods", json={"name": "x", "serving_desc": "1", "serving_g": 1, "nutrients": {}})
        assert r.status_code == 403 and r.json() == {"detail": "Missing X-Requested-With header"}
        r = bare.post("/api/foods", json={}, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 403
        assert bare.delete("/api/log/1").status_code == 403
        assert bare.put("/api/profile", json={"name": "x"}).status_code == 403
        assert bare.get("/api/profile").status_code == 200  # reads do not need it
        r = bare.post("/api/foods", json={"name": "x", "serving_desc": "1", "serving_g": 1, "nutrients": {}}, headers={"X-Requested-With": "kidney-health"})
        assert r.status_code == 201


def test_origin_must_match(client, tmp_path):
    body = {"name": "x", "serving_desc": "1", "serving_g": 1, "nutrients": {}}
    for origin in ("https://evil.example", "null", "http://localhost:9999", "https://localhost", "not a url"):
        r = client.post("/api/foods", json=body, headers={"Origin": origin})
        assert r.status_code == 403, origin
    assert client.post("/api/foods", json=body, headers={"Origin": "http://localhost"}).status_code == 201
    assert client.post("/api/foods", json=body, headers={"Origin": "http://LOCALHOST:80"}).status_code == 201


def test_origin_behind_tls_proxy_and_public_url(tmp_path):
    app = make_echo_app(tmp_path, public_url="https://kidney.example.org")
    # a proxy that rewrites Host: Origin is the public origin, Host is the upstream name
    with TestClient(app, base_url="http://10.0.0.5:8000", client=("127.0.0.1", 1)) as c:
        r = c.post("/api/echo", headers={"Origin": "https://kidney.example.org", "X-Requested-With": "kidney-health", "Host": "10.0.0.5:8000"})
        assert r.status_code == 200
        r = c.post("/api/echo", headers={"Origin": "https://other.example.org", "X-Requested-With": "kidney-health"})
        assert r.status_code == 403
    # without PUBLIC_URL, the effective scheme from a trusted proxy makes https origins match
    app = make_echo_app(tmp_path)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1)) as c:
        headers = {"Origin": "https://localhost", "X-Requested-With": "kidney-health"}
        assert c.post("/api/echo", headers=headers).status_code == 403
        assert c.post("/api/echo", headers={**headers, "X-Forwarded-Proto": "https"}).status_code == 200


def test_unsafe_non_api_requests_check_origin_but_not_the_custom_header(tmp_path):
    with TestClient(make_echo_app(tmp_path), headers={}) as c:
        assert c.post("/form").status_code == 200
        assert c.post("/form", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/form", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


# --------------------------------------------------------------------------- #
# Body limits
# --------------------------------------------------------------------------- #


def test_declared_oversized_body_is_413(client):
    r = client.post("/api/foods", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json() == {"detail": "Request body too large"}
    assert_security_headers(r)


def test_streamed_oversized_body_is_413(tmp_path):
    app = make_echo_app(tmp_path, max_body_bytes=2048)

    def chunks():
        for _ in range(10):
            yield b"y" * 512

    with TestClient(app) as c:
        r = c.post("/api/echo", content=chunks())
        assert r.status_code == 413 and r.json() == {"detail": "Request body too large"}
        assert c.post("/api/echo", content=b"z" * 2048).json()["size"] == 2048
        assert c.post("/api/echo", content=b"z" * 2049).status_code == 413
        r = c.post("/api/echo", content=b"{}", headers={"content-length": "-5"})
        assert r.status_code in (400, 413)


def test_registered_prefix_gets_the_image_limit(tmp_path):
    app = make_echo_app(tmp_path, max_body_bytes=1024, max_image_bytes=4096)
    security.register_body_limit("/api/echo", "max_image_bytes")
    try:
        with TestClient(app) as c:
            assert c.post("/api/echo", content=b"a" * 3000).json()["size"] == 3000
            assert c.post("/api/echo", content=b"a" * 5000).status_code == 413
    finally:
        security._BODY_LIMIT_OVERRIDES.remove(("/api/echo", "max_image_bytes"))
    with pytest.raises(ValueError):
        security.register_body_limit("/x", "no_such_setting")


# --------------------------------------------------------------------------- #
# API docs
# --------------------------------------------------------------------------- #


def test_docs_are_off_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_docs_when_enabled_get_a_relaxed_csp_only_there(tmp_path, foods_json):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, docs_enabled=True)
    with TestClient(create_app(settings)) as c:
        r = c.get("/docs")
        assert r.status_code == 200
        assert "'unsafe-inline'" in r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert c.get("/openapi.json").status_code == 200
        assert c.get("/api/profile").headers["content-security-policy"] == SPEC_CSP


# --------------------------------------------------------------------------- #
# Error and log redaction (N4)
# --------------------------------------------------------------------------- #


def test_validation_errors_never_echo_input(client):
    r = client.post("/api/log", json={"date": "not-a-date-SECRETISH", "meal": "brunch", "food_id": "abc", "servings": "lots"})
    assert r.status_code == 400
    body = r.json()
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["errors"] and all(set(e) == {"type", "loc", "msg"} for e in body["errors"])
    assert "SECRETISH" not in r.text and "lots" not in r.text


def test_secret_fields_are_not_echoed(tmp_path):
    with TestClient(make_echo_app(tmp_path)) as c:
        secret = "hunter2-correct-horse"
        r = c.post("/api/secret", json={"password": "short-pw-xyz", "api_key": ["not", "a", "string", secret]})
        assert r.status_code == 400
        assert "short-pw-xyz" not in r.text and secret not in r.text
        assert all("input" not in e and "ctx" not in e for e in r.json()["errors"])
        assert any(e["loc"] == ["body", "password"] and e["msg"] == "invalid value" for e in r.json()["errors"])
        r = c.post("/api/secret", content=b'{"password": "abc', headers={"content-type": "application/json"})
        assert r.status_code == 400 and "abc" not in r.text


def test_log_redaction(caplog):
    security.install_log_redaction(["sk-test-1234567890abcdef"])
    logger = logging.getLogger("kidney_health.test")
    with caplog.at_level(logging.INFO):
        logger.info("calling with key %s", "sk-test-1234567890abcdef")
        logger.info("Authorization: Bearer abc.def.ghi")
        logger.info("url https://api.example/?api_key=XYZ987&q=1")
        try:
            raise ValueError("boom sk-test-1234567890abcdef")
        except ValueError:
            logger.exception("failed")
    text = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert "sk-test-1234567890abcdef" not in text and "abc.def.ghi" not in text and "XYZ987" not in text
    assert text.count("[redacted]") >= 4
    assert caplog.records[0].args == ("[redacted]",)  # argument structure kept for formatters
    for name in security.HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_configured_secrets_are_redacted_from_app_logs(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, usda_api_key="usda-key-ABCDEFGHIJKL")
    with TestClient(create_app(settings)):
        with caplog.at_level(logging.INFO):
            logging.getLogger("kidney_health").warning("oops usda-key-ABCDEFGHIJKL leaked")
    assert "usda-key-ABCDEFGHIJKL" not in caplog.text
    assert "Settings(" in repr(settings) and "usda-key" not in repr(settings)


def test_split_host_header():
    assert security.split_host_header("Example.ORG:8000") == "example.org"
    assert security.split_host_header("[::1]:8000") == "::1"
    assert security.split_host_header("[::1]x") is None
    assert security.split_host_header("a:b:c") is None
    assert security.split_host_header("") is None
