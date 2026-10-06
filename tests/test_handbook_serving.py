"""The handbook at /learn (note 08 §4.6): mount, path-scoped CSP, cache headers, no sign-in, 404s,
traversal and symlink escapes, the start-up checks, GET /api/handbook and the two config keys.

Uses the tiny Material-shaped site in tests/fixtures/learn/ (copied to a temporary directory, so tests
can add files and symlinks). The real site is checked end to end by tools/e2e/learn.py in CI's
handbook job.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Iterator

import pytest

from app import handbook, security
from app.config import DEFAULT_HANDBOOK_DIR, ConfigError, Settings, load_settings
from app.main import create_app
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, HTTPS_URL, TestClient, make_settings, sign_in

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "learn"

SHARED = 'var palette=__md_get("__palette");palette&&document.body.setAttribute("data-md-color-scheme",palette.color.scheme)'
# Every inline script of the fixture: one scope script per directory depth (".", "..", "../..") plus the
# absolute one of 404.html, and one script shared by all pages. The JSON config block is not a script.
SCRIPTS = (
    '__md_scope=new URL(".",location)',
    '__md_scope=new URL("..",location)',
    '__md_scope=new URL("../..",location)',
    '__md_scope=new URL("/learn/",location)',
    SHARED,
)


def sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


EXPECTED_HASHES = sorted(sha256_source(s) for s in SCRIPTS)


def expected_policy(hashes: list[str]) -> str:
    return (
        "default-src 'self'; script-src 'self' " + " ".join(hashes) + "; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


@pytest.fixture
def site(tmp_path: Path) -> Path:
    target = tmp_path / "learn"
    shutil.copytree(FIXTURE, target)
    return target


def _client(settings: Settings, **kwargs) -> TestClient:
    return TestClient(create_app(settings), follow_redirects=False, **kwargs)


@pytest.fixture
def learn_client(tmp_path: Path, foods_json: Path, site: Path) -> Iterator[TestClient]:
    """An app serving the fixture site; nobody signed in (the first admin exists)."""
    with _client(make_settings(tmp_path, foods_json, handbook_dir=site)) as c:
        yield c


# --------------------------------------------------------------------------- hashes and the policy
def test_hashes_cover_exactly_the_inline_scripts_of_the_fixture(site: Path) -> None:
    assert list(handbook.inline_script_hashes(site)) == EXPECTED_HASHES


def test_script_types_src_and_case() -> None:
    html = (
        "<p>x</p><script>a()</script><script src='x.js'>ignored()</script>"
        "<script id='__config' type='application/json'>{\"a\": 1}</script><SCRIPT type=\"module\">b()</SCRIPT >"
        "<script type='text/javascript; charset=utf-8'>c()</script><script type='text/x-template'>d</script>"
        "<script type='importmap'>{}</script><script type=''>e()</script>"
    )
    assert handbook.inline_scripts(html) == ["a()", "b()", "c()", "{}", "e()"]


def test_hash_matches_the_browser_after_line_break_normalisation() -> None:
    assert handbook.script_hash("a()\r\nb()\rc()") == handbook.script_hash("a()\nb()\nc()") == sha256_source("a()\nb()\nc()")


def test_policy_text_is_exact_and_has_no_unsafe_inline_or_trusted_types(site: Path) -> None:
    policy = handbook.handbook_csp(handbook.inline_script_hashes(site))
    assert policy == expected_policy(EXPECTED_HASHES)
    assert "unsafe" not in policy and "trusted-types" not in policy


def test_more_than_the_limit_of_inline_scripts_raises(site: Path) -> None:
    with pytest.raises(handbook.HandbookError, match="more than 3 different inline scripts"):
        handbook.inline_script_hashes(site, limit=3)
    (site / "many.html").write_text("".join(f"<script>s{i}()</script>" for i in range(handbook.MAX_INLINE_SCRIPTS)), encoding="utf-8")
    with pytest.raises(handbook.HandbookError, match="refusing to build a Content-Security-Policy"):
        handbook.inline_script_hashes(site)


def test_a_page_that_is_not_utf8_raises(site: Path) -> None:
    (site / "bad.html").write_bytes(b"<script>\xff\xfe</script>")
    with pytest.raises(handbook.HandbookError, match="not UTF-8"):
        handbook.inline_script_hashes(site)


def test_pages_symlinked_from_outside_are_neither_hashed_nor_served(tmp_path: Path, foods_json: Path, site: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.html").write_text("<script>steal()</script>", encoding="utf-8")
    (outside / "secret.txt").write_text("top secret", encoding="utf-8")
    (site / "evil.html").symlink_to(outside / "evil.html")
    (site / "leak.txt").symlink_to(outside / "secret.txt")
    (site / "linked-dir").symlink_to(outside, target_is_directory=True)
    (site / "inside.html").symlink_to(site / "index.html")  # a link that stays inside is fine
    assert sha256_source("steal()") not in handbook.inline_script_hashes(site)
    with _client(make_settings(tmp_path, foods_json, handbook_dir=site)) as c:
        for path in ("/learn/evil.html", "/learn/leak.txt", "/learn/linked-dir/secret.txt", "/learn/linked-dir/evil.html"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert "top secret" not in r.text and "steal()" not in r.text
        assert c.get("/learn/inside.html").status_code == 200


# --------------------------------------------------------------------------- serving
def test_learn_is_public_and_serves_pages(learn_client: TestClient) -> None:
    r = learn_client.get("/learn/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>Start here</h1>" in r.text
    assert learn_client.get("/learn/eat/potassium/").status_code == 200
    assert learn_client.get("/api/me").status_code == 401  # nobody is signed in; /learn needed no session


def test_learn_without_slash_and_directories_redirect(learn_client: TestClient) -> None:
    r = learn_client.get("/learn")
    assert (r.status_code, r.headers["location"]) == (308, "/learn/")
    assert learn_client.get("/learn?q=x").headers["location"] == "/learn/?q=x"
    r = learn_client.get("/learn/stages")
    assert r.status_code == 307 and r.headers["location"].endswith("/learn/stages/")


def test_missing_page_is_the_sites_404(learn_client: TestClient) -> None:
    r = learn_client.get("/learn/no/such/page/")
    assert r.status_code == 404
    assert "<h1>Page not found</h1>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-security-policy"] == expected_policy(EXPECTED_HASHES)


def test_no_directory_listing(learn_client: TestClient) -> None:
    for path in ("/learn/assets/", "/learn/assets/javascripts/", "/learn/assets", "/learn/search/"):
        r = learn_client.get(path)
        assert r.status_code == 404, path
        assert "<h1>Page not found</h1>" in r.text  # the site's 404 page, not a listing
        assert "favicon.svg" not in r.text and "search_index.json" not in r.text


@pytest.mark.parametrize(
    "path",
    [
        "/learn/..%2f..%2fsecret.txt",
        "/learn/%2e%2e/%2e%2e/secret.txt",
        "/learn/%2e%2e%2fsecret.txt",
        "/learn/..%5csecret.txt",
        "/learn/%2fetc%2fpasswd",
        "/learn//etc/passwd",
        "/learn/%00",
        "/learn/assets/..%2f..%2f..%2fsecret.txt",
        "/learn/" + "a" * 5000,
    ],
)
def test_traversal_attempts_are_404(tmp_path: Path, learn_client: TestClient, path: str) -> None:
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    r = learn_client.get(path)
    assert r.status_code in (404, 400), (path, r.status_code)
    assert "top secret" not in r.text and "root:" not in r.text


def test_only_get_and_head(learn_client: TestClient) -> None:
    assert learn_client.head("/learn/").status_code == 200
    for method in ("POST", "PUT", "DELETE"):
        assert learn_client.request(method, "/learn/").status_code == 405, method


def test_cache_headers(learn_client: TestClient) -> None:
    immutable = "public, max-age=31536000, immutable"
    assert learn_client.get("/learn/assets/javascripts/bundle.0123abcd.min.js").headers["cache-control"] == immutable
    assert learn_client.get("/learn/assets/stylesheets/main.89abcdef.min.css").headers["cache-control"] == immutable
    for path in ("/learn/", "/learn/eat/potassium/", "/learn/assets/images/favicon.svg", "/learn/search/search_index.json",
                 "/learn/sitemap.xml", "/learn"):
        assert learn_client.get(path).headers["cache-control"] == "no-cache", path
    first = learn_client.get("/learn/")
    assert first.headers["etag"]
    again = learn_client.get("/learn/", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
    bundle = learn_client.get("/learn/assets/javascripts/bundle.0123abcd.min.js")
    assert bundle.headers["content-type"].startswith("text/javascript")
    again = learn_client.get(bundle.url, headers={"If-None-Match": bundle.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == immutable


@pytest.mark.parametrize(
    ("path", "fingerprinted"),
    [
        ("/learn/assets/javascripts/bundle.79ae519e.min.js", True),
        ("/learn/assets/javascripts/workers/search.2c215733.min.js", True),
        ("/learn/assets/stylesheets/palette.ab4e12ef.min.css", True),
        ("/learn/assets/javascripts/lunr/min/lunr.stemmer.support.min.js", False),
        ("/learn/assets/javascripts/bundle.79AE519E.min.js", False),
        ("/learn/eat/bundle.79ae519e.min.js", False),
        ("/assets/javascripts/bundle.79ae519e.min.js", False),
    ],
)
def test_fingerprint_pattern(path: str, fingerprinted: bool) -> None:
    assert (handbook.cache_control_for(path, 200) == handbook.IMMUTABLE) is fingerprinted
    assert handbook.cache_control_for(path, 404) == handbook.NO_CACHE


def test_gzip_files_are_labelled_as_gzip(tmp_path: Path, foods_json: Path, site: Path) -> None:
    (site / "sitemap.xml.gz").write_bytes(gzip.compress((site / "sitemap.xml").read_bytes()))
    with _client(make_settings(tmp_path, foods_json, handbook_dir=site)) as c:
        r = c.get("/learn/sitemap.xml.gz", headers={"Accept-Encoding": "identity"})
        assert r.status_code == 200 and r.headers["content-type"] == "application/gzip"


# --------------------------------------------------------------------------- headers: /learn vs the app
def test_learn_gets_its_own_csp_and_every_other_security_header(learn_client: TestClient) -> None:
    app_headers = learn_client.get("/").headers
    for path in ("/learn/", "/learn/eat/potassium/", "/learn/assets/javascripts/bundle.0123abcd.min.js", "/learn"):
        headers = learn_client.get(path).headers
        assert headers["content-security-policy"] == expected_policy(EXPECTED_HASHES), path
        for name, value in security.STATIC_HEADERS:
            assert headers[name] == value == app_headers[name], (path, name)
        assert "strict-transport-security" not in headers  # plain http


@pytest.mark.parametrize("path", ["/", "/index.html", "/sw.js", "/healthz", "/api/auth/status", "/api/me", "/learnmore",
                                  "/learning/", "/static/learn/", "/manifest.webmanifest"])
def test_the_app_policy_is_unchanged_everywhere_else(learn_client: TestClient, path: str) -> None:
    assert learn_client.get(path).headers["content-security-policy"] == security.CONTENT_SECURITY_POLICY


def test_https_adds_upgrade_and_hsts_on_learn_too(tmp_path: Path, foods_json: Path, site: Path) -> None:
    with _client(make_settings(tmp_path, foods_json, handbook_dir=site), base_url=HTTPS_URL) as c:
        learn = c.get("/learn/").headers
        assert learn["content-security-policy"] == expected_policy(EXPECTED_HASHES) + "; upgrade-insecure-requests"
        assert learn["strict-transport-security"] == "max-age=31536000"
        assert c.get("/").headers["content-security-policy"] == security.CONTENT_SECURITY_POLICY + "; upgrade-insecure-requests"


def test_path_policy_prefixes_are_checked() -> None:
    settings = Settings(data_dir=Path("unused"))
    for bad in ("learn", "/learn/", "/api/x", "/api"):
        with pytest.raises(ValueError):
            security.SecurityHeadersMiddleware(None, settings, path_policies=[(bad, "default-src 'none'")])
    mw = security.SecurityHeadersMiddleware(None, settings, path_policies=[("/learn", "P")])
    assert [mw.policy_for(p) for p in ("/learn", "/learn/", "/learn/x", "/learnx", "/")] == [
        "P", "P", "P", security.CONTENT_SECURITY_POLICY, security.CONTENT_SECURITY_POLICY]


# --------------------------------------------------------------------------- absent or broken site
def test_absent_site_is_404_with_the_app_policy(tmp_path: Path, foods_json: Path, caplog: pytest.LogCaptureFixture) -> None:
    missing = tmp_path / "no-site"
    with caplog.at_level(logging.INFO, logger="kidney_health.handbook"), \
            _client(make_settings(tmp_path, foods_json, handbook_dir=missing)) as c:
        for path in ("/learn", "/learn/", "/learn/eat/potassium/"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert r.headers["content-security-policy"] == security.CONTENT_SECURITY_POLICY
    assert "no built handbook at" in caplog.text and "Learn links" in caplog.text


def test_site_without_index_is_not_served(tmp_path: Path, foods_json: Path, site: Path, caplog: pytest.LogCaptureFixture) -> None:
    (site / "index.html").unlink()
    with caplog.at_level(logging.WARNING, logger="kidney_health.handbook"), \
            _client(make_settings(tmp_path, foods_json, handbook_dir=site)) as c:
        assert c.get("/learn/eat/potassium/").status_code == 404
    assert "has no index.html" in caplog.text


def test_a_broken_site_is_logged_and_not_served(tmp_path: Path, foods_json: Path, site: Path, caplog: pytest.LogCaptureFixture) -> None:
    (site / "many.html").write_text("".join(f"<script>s{i}()</script>" for i in range(80)), encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="kidney_health.handbook"), \
            _client(make_settings(tmp_path, foods_json, handbook_dir=site)) as c:
        assert c.get("/learn/").status_code == 404
        assert c.get("/healthz").status_code == 200  # the food log still starts
    assert "is not served" in caplog.text and "inline scripts" in caplog.text


def test_settings_built_in_code_have_no_handbook(tmp_path: Path, foods_json: Path) -> None:
    app = create_app(make_settings(tmp_path, foods_json))
    assert app.state.handbook is None


def test_mount_must_come_before_the_root_mount(tmp_path: Path, foods_json: Path, site: Path) -> None:
    app = create_app(make_settings(tmp_path, foods_json, handbook_dir=site))
    with pytest.raises(RuntimeError, match="before the '/' static mount"):
        handbook.mount(app, app.state.handbook)


# --------------------------------------------------------------------------- GET /api/handbook
def test_api_handbook_needs_a_session(learn_client: TestClient) -> None:
    assert learn_client.get("/api/handbook").status_code == 401


def test_api_handbook_when_served(learn_client: TestClient) -> None:
    sign_in(learn_client, ADMIN_USERNAME, ADMIN_PASSWORD)
    r = learn_client.get("/api/handbook")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert (body["available"], body["url"], body["public_url"]) == (True, "/learn/", None)
    links = body["links"]
    assert set(links) == {"nutrients", "flags", "pages"}
    assert links["nutrients"]["potassium_mg"] == {"path": "eat/potassium/", "title": "Potassium"}
    assert links["flags"]["phosphate_additive"]["path"] == "eat/phosphate-additives/"
    assert links["pages"]["home"]["path"] == ""
    assert links["pages"]["get_help_now"]["path"] == "get-help-now/"
    for group in links.values():
        for item in group.values():
            assert item["path"] == "" or re.fullmatch(r"[a-z0-9-]+(/[a-z0-9-]+)*/", item["path"]), item


@pytest.mark.parametrize("public", [None, "https://example.org/kh/"])
def test_api_handbook_without_a_site(tmp_path: Path, foods_json: Path, public: str | None) -> None:
    settings = make_settings(tmp_path, foods_json, handbook_dir=tmp_path / "none", handbook_public_url=public)
    with _client(settings) as c:
        sign_in(c)
        body = c.get("/api/handbook").json()
    assert (body["available"], body["url"], body["public_url"]) == (False, public, public)


def test_api_handbook_prefers_the_local_copy(tmp_path: Path, foods_json: Path, site: Path) -> None:
    settings = make_settings(tmp_path, foods_json, handbook_dir=site, handbook_public_url="https://example.org/kh/")
    with _client(settings) as c:
        sign_in(c)
        body = c.get("/api/handbook").json()
    assert (body["url"], body["public_url"]) == ("/learn/", "https://example.org/kh/")


# --------------------------------------------------------------------------- configuration
def test_handbook_dir_from_env_and_default(tmp_path: Path) -> None:
    assert load_settings({"DATA_DIR": str(tmp_path)}).handbook_dir == DEFAULT_HANDBOOK_DIR
    assert load_settings({"DATA_DIR": str(tmp_path), "HANDBOOK_DIR": "/app/learn"}).handbook_dir == Path("/app/learn")
    assert load_settings({"DATA_DIR": str(tmp_path), "HANDBOOK_DIR": "  "}).handbook_dir == DEFAULT_HANDBOOK_DIR


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("https://ksullivan86.github.io/kidney-health", "https://ksullivan86.github.io/kidney-health/"),
        ("HTTPS://Example.ORG:443/", "https://example.org/"),
        ("http://nas.lan:8080/learn/", "http://nas.lan:8080/learn/"),
    ],
)
def test_handbook_public_url_is_normalised(tmp_path: Path, raw: str, normalised: str) -> None:
    assert load_settings({"DATA_DIR": str(tmp_path), "HANDBOOK_PUBLIC_URL": raw}).handbook_public_url == normalised


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("ftp://example.org/", "http:// or https://"),
        ("javascript:alert(1)", "http:// or https://"),
        ("example.org/handbook", "http:// or https://"),
        ("https://user:pw@example.org/", "user name or password"),
        ("https://example.org/?x=1", "without ?query or #fragment"),
        ("https://example.org/#top", "without ?query or #fragment"),
        ("https://example.org:99999/", "not a valid URL"),
    ],
)
def test_handbook_public_url_rejects_bad_values(tmp_path: Path, raw: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)) as exc:
        load_settings({"DATA_DIR": str(tmp_path), "HANDBOOK_PUBLIC_URL": raw})
    assert "HANDBOOK_PUBLIC_URL" in str(exc.value)
