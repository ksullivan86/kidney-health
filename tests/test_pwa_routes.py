"""Server side of the installable app (note 02 R4, R6): /sw.js, content types, cache headers, public paths."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import pwa
from app.config import Settings
from app.main import create_app

from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, DAY, TestClient, sign_in

SW_TEMPLATE = "const VERSION = '__VERSION__';\nconst SHELL = `kdl-shell-${VERSION}`;\nself.addEventListener('fetch', () => {});\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_static(root: Path) -> Path:
    static = root / "static"
    (static / "icons").mkdir(parents=True)
    (static / "js").mkdir()
    (static / "vendor").mkdir()
    (static / "index.html").write_text("<!doctype html><title>Kidney</title><script src=/js/app.js></script>", encoding="utf-8")
    (static / "sw.js").write_text(SW_TEMPLATE, encoding="utf-8")
    (static / "manifest.webmanifest").write_text('{"id": "/", "start_url": "/", "display": "standalone"}', encoding="utf-8")
    (static / "icons" / "icon-192.png").write_bytes(PNG)
    (static / "icons" / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (static / "apple-touch-icon.png").write_bytes(PNG)
    (static / "js" / "app.js").write_text("'use strict';\n" + "// padding\n" * 300, encoding="utf-8")
    (static / "vendor" / "zxing_reader.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    return static


@pytest.fixture
def static(tmp_path: Path) -> Path:
    return make_static(tmp_path)


def app_client(tmp_path: Path, foods_json: Path, static: Path, **kw) -> TestClient:
    kw.setdefault("admin_username", ADMIN_USERNAME)
    kw.setdefault("admin_password", ADMIN_PASSWORD)
    return TestClient(create_app(Settings(data_dir=tmp_path / "data", foods_json=foods_json, static_dir=static, **kw)))


def test_service_worker_is_versioned_and_not_cached(tmp_path, foods_json, static):
    with app_client(tmp_path, foods_json, static) as c:
        r = c.get("/sw.js")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/javascript; charset=utf-8"
        assert r.headers["cache-control"] == "no-cache"
        assert "content-security-policy" in r.headers
        version = re.search(r"const VERSION = '([0-9a-f]+)';", r.text).group(1)
        assert len(version) == 12 and version == pwa.shell_version(static)
        assert "__VERSION__" not in r.text
        assert c.app.state.pwa.version == version


def test_version_changes_when_a_shell_file_changes(tmp_path, foods_json, static):
    first = pwa.shell_version(static)
    assert pwa.shell_version(static) == first  # deterministic
    (static / "js" / "app.js").write_text("'use strict'; // release 2\n", encoding="utf-8")
    second = pwa.shell_version(static)
    assert second != first
    (static / "css").mkdir()
    (static / "css" / "base.css").write_text("body{}", encoding="utf-8")
    assert pwa.shell_version(static) not in (first, second)
    (static / ".DS_Store").write_bytes(b"junk")  # hidden files do not count
    third = pwa.shell_version(static)
    (static / ".DS_Store").write_bytes(b"other junk")
    assert pwa.shell_version(static) == third
    with app_client(tmp_path, foods_json, static) as c:
        assert f"'{third}'" in c.get("/sw.js").text


def test_kill_switch(tmp_path, foods_json, static):
    with app_client(tmp_path, foods_json, static, pwa_enabled=False) as c:
        r = c.get("/sw.js")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert "registration.unregister()" in r.text and "caches.delete" in r.text
        assert "__VERSION__" not in r.text and "fetch" not in r.text


def test_missing_template_is_404(tmp_path, foods_json, static):
    (static / "sw.js").unlink()
    with app_client(tmp_path, foods_json, static) as c:
        assert c.get("/sw.js").status_code == 404


def test_static_content_types_and_cache_headers(tmp_path, foods_json, static):
    with app_client(tmp_path, foods_json, static) as c:
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/manifest+json"
        assert r.headers["cache-control"] == "no-cache"
        for path, kind in (("/icons/icon-192.png", "image/png"), ("/apple-touch-icon.png", "image/png"),
                           ("/icons/icon.svg", "image/svg+xml"), ("/vendor/zxing_reader.wasm", "application/wasm")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.headers["content-type"].startswith(kind), path
            assert r.headers["cache-control"] == "public, max-age=604800", path
        r = c.get("/")
        assert r.headers["cache-control"] == "no-cache" and r.headers["content-type"].startswith("text/html")
        r = c.get("/js/app.js")
        assert r.headers["content-type"] == "text/javascript; charset=utf-8" and r.headers["cache-control"] == "no-cache"
        # revalidation keeps the headers
        etag = r.headers["etag"]
        r = c.get("/js/app.js", headers={"If-None-Match": etag})
        assert r.status_code == 304 and r.headers["cache-control"] == "no-cache"
        assert c.get("/api/profile").headers["cache-control"] == "no-store"


def test_pwa_paths_and_the_shell_are_public_but_the_api_needs_a_session(tmp_path, foods_json, static):
    """v0.3: static files carry no data, so the shell, manifest, icons and /sw.js load before sign-in
    (iOS fetches the icon at install time); every /api route but the public auth ones needs a session."""
    with app_client(tmp_path, foods_json, static) as c:
        for path in ("/sw.js", "/manifest.webmanifest", "/icons/icon-192.png", "/apple-touch-icon.png", "/healthz", "/", "/js/app.js"):
            assert c.get(path).status_code == 200, path
        assert c.get("/api/profile").status_code == 401
        assert c.get("/api/auth/status").status_code == 200
        assert c.get("/sw.js", headers={"Host": "evil.example"}).status_code == 400


def test_is_public_path():
    assert pwa.is_public_path("/sw.js") and pwa.is_public_path("/icons/x.png") and pwa.is_public_path("/healthz")
    assert not pwa.is_public_path("/") and not pwa.is_public_path("/api/profile") and not pwa.is_public_path("/iconsX")


def test_static_is_gzipped_but_api_is_not(tmp_path, foods_json, static):
    with app_client(tmp_path, foods_json, static) as c:
        sign_in(c)
        r = c.get("/js/app.js", headers={"Accept-Encoding": "gzip"})
        assert r.headers.get("content-encoding") == "gzip"
        assert r.text.startswith("'use strict'")  # the client decodes it
        r = c.get("/api/log/range", params={"start": "2026-01-01", "end": DAY}, headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and len(r.content) > 1024
        assert "content-encoding" not in r.headers


def test_real_static_dir_template_if_present(client):
    """When the frontend ships app/static/sw.js, the served worker carries a real version."""
    template = Path(pwa.__file__).resolve().parent / "static" / "sw.js"
    r = client.get("/sw.js")
    if not template.exists():
        assert r.status_code == 404
        return
    assert r.status_code == 200 and "__VERSION__" not in r.text
    assert client.app.state.pwa.version in r.text

