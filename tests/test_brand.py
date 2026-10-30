"""The brand strings (design note 14, change 3; ``app/brand.py`` and its browser twin ``app/static/js/engine/brand.js``).

Covered: every constant keeps its current value; the sites that used to spell a value out still produce exactly it; the Python and
JavaScript copies agree where they overlap; the browser loads its copy before any script that reads it; and the main literals are not
spelled out again in the code (a short, explicit allowlist names the few places that must). No network."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import account, admin, brand, crypto, data_import, foods, off, pwa, security, settings_registry
from app.ai import client as ai_client
from app.ai import config as ai_config
from app.auth import api_tokens, sessions, throttle
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
STATIC = APP / "static"
BRAND_JS = STATIC / "js" / "engine" / "brand.js"

# --------------------------------------------------------------------------- the values

# WARNING: do not "fix" a value here to match a changed constant. Most of these are already on disk, on the wire or in someone's
# browser: a new cookie name signs everyone out, a new token prefix or realm breaks every token made, a new HKDF label makes the
# stored API keys unreadable, a new database name starts an empty database, a new export format makes every export file people
# kept unreadable to the import. A new product picks its values before its first start; an install in use keeps these.
PINNED = {
    "NAME": "Kidney Health",
    "SCREEN_NAME": "Kidney Diet Log",
    "SLUG": "kidney-health",
    "PROJECT_URL": "https://github.com/ksullivan86/kidney-health",
    "LOG_CSV_PREFIX": "kidney-log_",
    "LOGGER_NAME": "kidney_health",
    "DB_FILENAME": "kidney.db",
    "BACKUP_PREFIX": "kidney-",
    "SESSION_COOKIE": "kh_session",
    "SESSION_COOKIE_HOST": "__Host-kh_session",
    "DEVICE_COOKIE": "kh_device",
    "DEVICE_COOKIE_HOST": "__Host-kh_device",
    "OIDC_COOKIE": "kh_oidc",
    "OIDC_COOKIE_HOST": "__Host-kh_oidc",
    "CSRF_HEADER_VALUE": "kidney-health",
    "VERSION_HEADER": "X-KDL-Version",
    "ASSISTANT_TOKEN_PREFIX": "kha_",
    "DEVICE_TOKEN_PREFIX": "khd_",
    "PAIRING_SCHEME": "kidneyhealthsync",
    "BEARER_REALM": "kidney-health",
    "MCP_SERVER_NAME": "kidney-health",
    "MCP_SERVER_TITLE": "Kidney Health food log",
    "MCP_SOURCE": "kidney-health",
    "EXPORT_FORMAT": "kidney-health-export",
    "USER_AGENT_AI": "kidney-health/{version}",
    "USER_AGENT_USDA": "kidney-health/0.3 (self-hosted food log)",
    "USER_AGENT_OFF": "KidneyHealth/{version} ({contact})",
    "USER_AGENT_HIBP": "kidney-health",
    "USER_AGENT_OIDC": "kidney-health",
    "HKDF_SECRETS_INFO": b"kidney-health/v1/secrets",
    "HKDF_LOGIN_FAILURES_INFO": "kidney-health/v1/login-failures",
    "HKDF_DEVICE_INFO": "kidney-health/v1/device",
    "HKDF_OPENAI_SAFETY_ID_INFO": "kidney-health/v1/openai-safety-id",
    "HKDF_AI_KEY_FINGERPRINT_INFO": "kidney-health/v1/ai-key-fingerprint",
}


def _constants() -> dict[str, object]:
    return {name: value for name, value in vars(brand).items() if name.isupper() and not name.startswith("_")}


def test_every_constant_keeps_its_value() -> None:
    assert _constants() == PINNED


def test_a_new_constant_must_be_pinned_here() -> None:
    """The comparison above already fails on an extra constant; this names the reason."""
    assert set(_constants()) - set(PINNED) == set(), "pin the new constant in PINNED (with the value it is meant to keep)"


def test_brand_py_imports_nothing_from_the_app() -> None:
    """Any module may import it, including config and crypto, so it must not import them back."""
    tree = ast.parse((APP / "brand.py").read_text(encoding="utf-8"))
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert [n.module for n in imports] == ["__future__"]


# --------------------------------------------------------------------------- the sites still produce the same values


def test_cookies_tokens_and_headers() -> None:
    assert (sessions.COOKIE_HTTP, sessions.COOKIE_HTTPS) == ("kh_session", "__Host-kh_session")
    assert (throttle.DEVICE_HTTP, throttle.DEVICE_HTTPS) == ("kh_device", "__Host-kh_device")
    assert security.CSRF_HEADER == "X-Requested-With" and security.CSRF_HEADER_VALUE == "kidney-health"
    assert pwa.VERSION_HEADER == "X-KDL-Version"
    assert (api_tokens.PREFIX, api_tokens.DEVICE_PREFIX) == ("kha_", "khd_")
    assert api_tokens.CHALLENGE == 'Bearer realm="kidney-health"'
    body = "A" * 43
    assert api_tokens.TOKEN_RE.pattern == "^kha_[A-Za-z0-9_-]{43}$" and api_tokens.DEVICE_TOKEN_RE.pattern == "^khd_[A-Za-z0-9_-]{43}$"
    assert api_tokens.TOKEN_RE.fullmatch(f"kha_{body}") and not api_tokens.TOKEN_RE.fullmatch(f"khd_{body}")
    assert api_tokens.DEVICE_TOKEN_RE.fullmatch(f"khd_{body}") and not api_tokens.DEVICE_TOKEN_RE.fullmatch(f"kha_{body}")
    assert api_tokens.new_token(api_tokens.ASSISTANT).startswith("kha_") and api_tokens.new_token(api_tokens.DEVICE).startswith("khd_")


def test_log_redaction_still_hides_both_token_families() -> None:
    body = "B" * 43
    assert security.redact(f"got kha_{body} here") == f"got kha_{security.REDACTED} here"
    assert security.redact(f"got khd_{body} here") == f"got khd_{security.REDACTED} here"
    assert security.redact(f"got kha_{body[:-1]} here") == f"got kha_{body[:-1]} here"  # 42 characters: not a token


def test_files_and_names() -> None:
    from app.config import DB_FILENAME

    assert DB_FILENAME == "kidney.db"
    assert account.EXPORT_FORMAT == data_import.EXPORT_FORMAT == "kidney-health-export"
    assert account.export_filename("bob").startswith("kidney-health-bob-") and account.export_filename("bob").endswith(".zip")
    assert admin.BACKUP_NAME.fullmatch("kidney-20261022T093000Z.db") and not admin.BACKUP_NAME.fullmatch("other-20261022T093000Z.db")
    assert account.README.startswith("Kidney Health export\n====================\n")
    assert '(\"kidney-health-export\", version 1)' in account.README
    assert mcp_server.SERVER_NAME == "kidney-health" and mcp_server.SERVER_TITLE == "Kidney Health food log"
    assert mcp_tools.SOURCE == "kidney-health"
    assert settings_registry.get("instance.name").default == "Kidney Health"
    assert settings_registry.get("food.off_contact").default == off.DEFAULT_CONTACT == "https://github.com/ksullivan86/kidney-health"


def test_import_refusals_still_name_the_product_and_the_format() -> None:
    with pytest.raises(data_import.ImportRefused) as bad_format:
        data_import.parse_export(json.dumps({"format": "something-else", "version": 1}).encode("utf-8"))
    assert str(bad_format.value) == 'This is not a Kidney Health export (its "format" is not "kidney-health-export").'
    with pytest.raises(data_import.ImportRefused) as not_object:
        data_import.parse_export(b"[]")
    assert str(not_object.value) == "This is not a Kidney Health export: the file must hold one JSON object."
    assert data_import.TOO_DEEP == "This is not a Kidney Health export: the file is nested too deeply."
    # a pydantic Literal needs the text itself, so the model keeps its own copy; it must equal the constant
    assert data_import.ExportFile.model_fields["format"].annotation.__args__ == (brand.EXPORT_FORMAT,)


def test_user_agents() -> None:
    assert ai_client.APP_USER_AGENT.format(version="1.2.3") == "kidney-health/1.2.3"
    assert off.user_agent("1.2.3", "me@example.org") == "KidneyHealth/1.2.3 (me@example.org)"
    with foods.usda_client() as client:
        assert client.headers["User-Agent"] == "kidney-health/0.3 (self-hosted food log)"


def test_loggers_keep_their_names() -> None:
    import logging

    from app import db, main

    assert main.logger.name == "kidney_health"
    assert db.log.name == "kidney_health.db" and ai_client.log.name == "kidney_health.ai" and throttle.log.name == "kidney_health.auth.throttle"
    assert logging.getLogger("kidney_health.crypto") is crypto.log


# A fixed key line, so the expected bytes below are computed without the code under test.
KEY_LINE = "q7IoAws2xpTotdPphqatpFvs4j12rG1DT0eeDPLz7jk"


def _hkdf(info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(KEY_LINE.encode("utf-8"))


def test_derived_keys_are_the_ones_a_running_install_already_uses() -> None:
    ring = crypto.Keyring([KEY_LINE])
    assert ring.ids[0] == hashlib.sha256(_hkdf(b"kidney-health/v1/secrets")).hexdigest()[:8]  # the stored API keys' key
    assert crypto.SECRETS_INFO == b"kidney-health/v1/secrets"
    assert (throttle.NAME_MAC_INFO, throttle.DEVICE_INFO) == ("kidney-health/v1/login-failures", "kidney-health/v1/device")
    assert (ai_config.SAFETY_ID_INFO, ai_config.KEY_FINGERPRINT_INFO) == ("kidney-health/v1/openai-safety-id", "kidney-health/v1/ai-key-fingerprint")
    for info in (throttle.NAME_MAC_INFO, throttle.DEVICE_INFO, ai_config.SAFETY_ID_INFO, ai_config.KEY_FINGERPRINT_INFO):
        assert ring.subkey(info) == _hkdf(info.encode("utf-8")), info


def test_the_api_document_still_names_the_cookie_and_the_prefixes() -> None:
    """``docs/api/openapi.json`` is checked in and compared with the live document by test_openapi_snapshot.py; this names what
    the brand constants feed into it."""
    doc = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    schemes = doc["components"]["securitySchemes"]
    assert schemes["session"]["name"] == "kh_session"
    assert schemes["assistantToken"]["bearerFormat"] == "kha_ followed by 43 characters"
    assert schemes["deviceToken"]["bearerFormat"] == "khd_ followed by 43 characters"
    assert "X-Requested-With: kidney-health" in schemes["session"]["description"]
    assert doc["info"]["title"] == "Kidney Health Food Log"


# --------------------------------------------------------------------------- the browser's copy


def _js_brand() -> dict[str, str]:
    text = BRAND_JS.read_text(encoding="utf-8")
    body = text[text.index("KH.brand = Object.freeze({"):]
    body = body[: body.index("});")]
    return dict(re.findall(r"^\s+(\w+): '([^']*)',", body, re.M))


# What only the browser has: the IndexedDB database of the offline copy.
JS_ONLY = {"idbName": "kdl"}


def _camel_to_constant(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).upper()


def test_the_browser_copy_has_the_same_values_where_it_overlaps() -> None:
    js = _js_brand()
    shared = {key: value for key, value in js.items() if key not in JS_ONLY}
    assert shared, "the twin shares nothing with app/brand.py"
    for key, value in shared.items():
        constant = _camel_to_constant(key)
        assert constant in PINNED, f"KH.brand.{key} has no Python constant {constant}"
        assert value == getattr(brand, constant), f"KH.brand.{key} differs from brand.{constant}"
    for key, value in JS_ONLY.items():
        assert js[key] == value
    assert set(js) == set(shared) | set(JS_ONLY)


def test_the_browser_copy_is_frozen_and_registered_before_its_readers() -> None:
    text = BRAND_JS.read_text(encoding="utf-8")
    assert "KH.brand = Object.freeze({" in text and "'use strict'" in text
    assert not re.search(r"\b(?:eval|innerHTML|fetch)\b", text.split("(() => {", 1)[1]), "the brand file only holds strings"
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', index)
    at = scripts.index("js/engine/brand.js")
    assert scripts[at + 1] == "js/core.js"  # the last engine file, right before core.js, which is the first script to read it
    for reader in ("js/core.js", "js/offline.js", "js/mock/export.js", "js/mock/import.js", "js/pwa.js", "js/main.js"):
        assert at < scripts.index(reader), reader
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "  '/js/engine/brand.js',\n" in sw


def test_the_preview_build_carries_the_browser_copy_before_its_readers(tmp_path: Path) -> None:
    """scripts/build_preview.py reads index.html, so it needs no list of its own; this shows the file arrives, in order."""
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    out = tmp_path / "preview.html"
    assert builder.main(["--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert html.count("KH.brand = Object.freeze({") == 1
    assert html.index("/* js/engine/guidance/hypo.js */") < html.index("/* js/engine/brand.js */") < html.index("/* js/core.js */")
    assert html.index("/* js/engine/brand.js */") < html.index("/* js/mock/export.js */")


READERS = {
    "js/core.js": ("KH.brand.csrfHeaderValue", "KH.brand.versionHeader"),
    "js/offline.js": ("KH.brand.idbName", "KH.brand.versionHeader"),
    "js/pwa.js": ("KH.brand.idbName",),
    "js/views/ai.js": ("KH.brand.csrfHeaderValue",),
    "js/views/ask-voice.js": ("KH.brand.csrfHeaderValue",),
    "js/mock/export.js": ("KH.brand.exportFormat",),
    "js/mock/import.js": ("KH.brand.exportFormat", "KH.brand.name"),
    "js/main.js": ("KH.brand.screenName",),
    "js/views/auth.js": ("KH.brand.screenName", "KH.brand.name"),
    "js/views/visit.js": ("KH.brand.screenName",),
    "js/views/settings.js": ("KH.brand.slug", "KH.brand.name"),
    "js/views/trends.js": ("KH.brand.logCsvPrefix",),
}


@pytest.mark.parametrize("path", sorted(READERS))
def test_the_scripts_read_the_browser_copy(path: str) -> None:
    text = (STATIC / path).read_text(encoding="utf-8")
    for needle in READERS[path]:
        assert needle in text, f"{path} should read {needle}"


# --------------------------------------------------------------------------- the literals stay in one place

# The compatibility literals. A string in the code that contains one of them is a place that spells a brand value out.
# Display names such as "Kidney Health" in the AI prompts are not on this list: they are prose.
PY_LITERALS = ("kh_session", "kh_device", "kha_", "khd_", "kidney.db", "kidney-health", "kidney_health", "X-KDL-Version", "KidneyHealth/", "kidney-log_")
JS_LITERALS = ("kh_session", "kha_", "khd_", "kidney.db", "kidney-health", "X-KDL-Version", "kidney-log_")

# Where a literal may stay, and why. Tests, docs, deploy files, tools/e2e and migrations (released steps are never edited) are not
# scanned at all: they state the values on purpose. Every entry here must still match something (checked below), so the list cannot rot.
PY_ALLOWED = {
    "app/auth/passwords.py": "the text of the start-up password self-test; it is hashed once and thrown away",
    "app/auth/policy.py": "APP_WORDS: the words a password may not contain; the demo's js/mock/auth.js has the same list",
    "app/data_import.py": "the Literal in ExportFile, which needs the text itself (test_import_refusals_still_name_the_product_and_the_format)",
    "app/mcp/server.py": "INSTRUCTIONS: the sentence read by the assistant, which says 'kidney-health food log'",
    "app/config.py": "the example address in the HANDBOOK_PUBLIC_URL error message",
}
JS_ALLOWED = {
    "js/mock/auth.js": "APP_WORDS, the twin of app/auth/policy.py",
    "js/mock/persist.js": "the demo's own stored copy: the 'kdl-demo-local' database and its 'kidney-health-demo-local' format, already in browsers",
    "js/engine/settings.js": "defaults of the settings registry, a vector-checked twin of app/settings_registry.py (the project address)",
    "js/engine/off.js": "METHOD_URL, a vector-checked twin of app/off.py (the project address)",
    "js/views/settings.js": "the link to app/off.py on the project page",
}


def _describe(hits: dict[str, list[str]]) -> str:
    return "\n".join(f"{path}: {line}" for path, lines in hits.items() for line in lines)


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _python_hits() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/static/" in rel or rel.startswith("app/migrations/") or rel == "app/brand.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                for literal in PY_LITERALS:
                    if literal in node.value:
                        hits.setdefault(rel, []).append(f"line {node.lineno}: {literal!r} in {node.value[:60]!r}")
    return hits


# One pass over a script: strings and comments, in the order they appear, so that a quote inside a comment is not a string.
JS_TOKEN = re.compile(r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`|/\*.*?\*/|//[^\n]*""", re.S)


def _javascript_hits() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in sorted((STATIC / "js").rglob("*.js")) + [STATIC / "sw.js", STATIC / "theme-init.js"]:
        rel = path.relative_to(STATIC).as_posix()
        if rel == "js/engine/brand.js":
            continue
        text = path.read_text(encoding="utf-8")
        for match in JS_TOKEN.finditer(text):
            token = match.group(0)
            if token.startswith(("/*", "//")):
                continue
            line = text.count("\n", 0, match.start()) + 1
            for literal in JS_LITERALS:
                if literal in token:
                    hits.setdefault(rel, []).append(f"line {line}: {literal!r} in {token[:60]!r}")
            if token[1:-1] == "kdl":
                hits.setdefault(rel, []).append(f"line {line}: the IndexedDB name 'kdl'")
    return hits


def test_python_spells_no_brand_literal_outside_brand_py() -> None:
    hits = _python_hits()
    stray = {path: lines for path, lines in hits.items() if path not in PY_ALLOWED}
    assert not stray, "use app/brand.py (or add the file to PY_ALLOWED with a reason):\n" + _describe(stray)
    assert set(PY_ALLOWED) <= set(hits), f"stale PY_ALLOWED entries: {sorted(set(PY_ALLOWED) - set(hits))}"


def test_javascript_spells_no_brand_literal_outside_brand_js() -> None:
    hits = _javascript_hits()
    stray = {path: lines for path, lines in hits.items() if path not in JS_ALLOWED}
    assert not stray, "use KH.brand (or add the file to JS_ALLOWED with a reason):\n" + _describe(stray)
    assert set(JS_ALLOWED) <= set(hits), f"stale JS_ALLOWED entries: {sorted(set(JS_ALLOWED) - set(hits))}"
