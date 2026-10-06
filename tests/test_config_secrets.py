"""Configuration: the *_FILE rule, validation with clear messages, SECRET_KEY parsing and rotation."""
from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app import config, crypto
from app.config import ConfigError, Settings, load_settings, read_secret
from app.main import create_app

from conftest import TestClient

REPO = Path(__file__).resolve().parent.parent
KEY_A = "a" * 32 + "-first-key-line"
KEY_B = "b" * 32 + "-second-key-line"


def env_with(tmp_path: Path, **values: str) -> dict[str, str]:
    return {"DATA_DIR": str(tmp_path / "data"), **values}


# --------------------------------------------------------------------------- #
# *_FILE
# --------------------------------------------------------------------------- #


def test_file_secret_is_read_and_trailing_newlines_stripped(tmp_path):
    f = tmp_path / "usda"
    f.write_text("file-key-123\r\n\n", encoding="utf-8")
    s = load_settings(env_with(tmp_path, USDA_API_KEY_FILE=str(f)))
    assert s.usda_api_key == "file-key-123"
    assert read_secret({"X_FILE": str(f)}, "X") == ("file-key-123", "file", f)


def test_inner_whitespace_of_a_file_secret_is_kept(tmp_path):
    f = tmp_path / "pw"
    f.write_text("  pass word  \n", encoding="utf-8")
    assert load_settings(env_with(tmp_path, APP_PASSWORD_FILE=str(f))).app_password == "  pass word  "


def test_setting_both_is_a_startup_error(tmp_path):
    f = tmp_path / "usda"
    f.write_text("from-file", encoding="utf-8")
    with pytest.raises(ConfigError, match="USDA_API_KEY or USDA_API_KEY_FILE, not both"):
        load_settings(env_with(tmp_path, USDA_API_KEY="from-env", USDA_API_KEY_FILE=str(f)))


def test_empty_file_means_unset_and_empty_env_does_not_conflict(tmp_path):
    f = tmp_path / "empty"
    f.write_text("\n", encoding="utf-8")
    assert load_settings(env_with(tmp_path, APP_PASSWORD_FILE=str(f))).app_password is None
    g = tmp_path / "pw"
    g.write_text("s3cret", encoding="utf-8")
    # APP_PASSWORD= (empty) in a compose file plus a file secret is fine
    assert load_settings(env_with(tmp_path, APP_PASSWORD="", APP_PASSWORD_FILE=str(g))).app_password == "s3cret"


@pytest.mark.parametrize("make", ["missing", "directory"])
def test_unreadable_file_names_the_key(tmp_path, make):
    target = tmp_path / "nope"
    if make == "directory":
        target.mkdir()
    with pytest.raises(ConfigError, match="SECRET_KEY_FILE"):
        load_settings(env_with(tmp_path, SECRET_KEY_FILE=str(target)))


def test_every_secret_supports_file(tmp_path):
    files = {}
    for name in ("USDA_API_KEY", "APP_PASSWORD", "ADMIN_PASSWORD", "TRUSTED_PROXY_SECRET", "SECRET_KEY"):
        f = tmp_path / name.lower()
        f.write_text((KEY_A if name in ("SECRET_KEY", "TRUSTED_PROXY_SECRET") else f"{name}-value") + "\n", encoding="utf-8")
        files[f"{name}_FILE"] = str(f)
    s = load_settings(env_with(tmp_path, ADMIN_USERNAME="owner", **files))
    assert (s.usda_api_key, s.app_password, s.admin_password) == ("USDA_API_KEY-value", "APP_PASSWORD-value", "ADMIN_PASSWORD-value")
    assert s.trusted_proxy_secret == KEY_A and s.secret_key == KEY_A
    assert s.secret_key_source == "file" and s.secret_key_file == Path(files["SECRET_KEY_FILE"])
    # secrets never show up in repr and are all registered for log redaction
    text = repr(s)
    assert "value" not in text and KEY_A not in text
    assert set(s.secret_values()) >= {"USDA_API_KEY-value", "APP_PASSWORD-value", "ADMIN_PASSWORD-value", KEY_A}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_defaults(tmp_path):
    s = load_settings(env_with(tmp_path))
    assert s.auth_mode == "local" and s.trusted_proxies == ("127.0.0.1", "::1")
    assert s.allowed_hosts == () and s.public_url is None and s.allow_insecure_http is None
    assert s.max_body_bytes == 1_048_576 and s.max_image_bytes == 4_194_304 and s.hsts_max_age == 31_536_000
    assert s.docs_enabled is False and s.pwa_enabled is True and s.secret_key_source == "auto"
    assert s.secret_key_path == tmp_path / "data" / "secret.key"
    assert s.admin_username is None  # no default admin name (note 07 §9 N3)
    assert s.warnings == ()


@pytest.mark.parametrize(
    "env, message",
    [
        ({"AUTH_MODE": "ldap"}, "AUTH_MODE must be one of local, proxy, none"),
        ({"PWA_ENABLED": "maybe"}, "PWA_ENABLED must be true or false"),
        ({"MAX_BODY_BYTES": "lots"}, "MAX_BODY_BYTES must be a whole number"),
        ({"MAX_BODY_BYTES": "10"}, "MAX_BODY_BYTES must be between"),
        ({"SESSION_MAX_DAYS": "90"}, "SESSION_MAX_DAYS must be between 1 and 30"),
        ({"PASSWORD_HASH": "md5"}, "PASSWORD_HASH must be one of"),
        ({"LOG_LEVEL": "loud"}, "LOG_LEVEL must be one of"),
        ({"PUBLIC_URL": "kidney.example.org"}, "PUBLIC_URL must look like https://"),
        ({"PUBLIC_URL": "https://kidney.example.org/app"}, "site root"),
        ({"PUBLIC_URL": "https://user:pw@kidney.example.org"}, "user name or password"),
        ({"ALLOWED_HOSTS": "https://kidney.example.org"}, "without a scheme, port or path"),
        ({"ALLOWED_HOSTS": "kidney.example.org:8000"}, "without a scheme, port or path"),
        ({"ALLOWED_HOSTS": "a.*.example.org"}, "is not a host name"),
        ({"TRUSTED_PROXIES": "*"}, "would let every client forge"),
        ({"TRUSTED_PROXIES": "my-proxy"}, "is not an IP address or CIDR"),
        ({"TRUSTED_PROXY_USER_HEADER": "Remote User"}, "must be an HTTP header name"),
        ({"SECRET_KEY": "short"}, "key line 1 is 5 characters long"),
        ({"SECRET_KEY": f"{KEY_A}\nshort-line"}, "key line 2"),
        ({"SECRET_KEY": "# only a comment"}, "contains no key"),
        ({"ADMIN_PASSWORD": "a long admin password"}, "needs ADMIN_USERNAME"),
        ({"ADMIN_USERNAME": "my admin", "ADMIN_PASSWORD": "x" * 20}, "ADMIN_USERNAME must be 3 to 64 characters"),
        ({"ALLOW_PRIVATE_AI_HOSTS": "true"}, "replaced by AI_PRIVATE_HOSTS"),
        ({"ENABLE_API_DOCS": "true", "DOCS_ENABLED": "false"}, "disagree"),
    ],
)
def test_invalid_settings_fail_with_a_clear_message(tmp_path, env, message):
    with pytest.raises(ConfigError, match=message.replace("(", r"\(").replace("*", r"\*")):
        load_settings(env_with(tmp_path, **env))


def test_invalid_secret_key_message_does_not_echo_the_key(tmp_path):
    with pytest.raises(ConfigError) as info:
        load_settings(env_with(tmp_path, SECRET_KEY="tooShortSecretValue"))
    assert "tooShortSecretValue" not in str(info.value)


def test_normalised_lists_and_urls(tmp_path):
    s = load_settings(
        env_with(
            tmp_path,
            ALLOWED_HOSTS="Kidney.Example.org., *.lan.example  192.168.1.10,[::1]",
            PUBLIC_URL="HTTPS://Kidney.Example.org:443/",
            TRUSTED_PROXIES="10.0.0.1/8, ::1 ,127.0.0.1",
            ALLOW_INSECURE_HTTP="false",
            DOCS_ENABLED="yes",
        )
    )
    assert s.allowed_hosts == ("kidney.example.org", "*.lan.example", "192.168.1.10", "::1")
    assert s.public_url == "https://kidney.example.org" and s.public_origin == "https://kidney.example.org"
    assert s.public_host == "kidney.example.org"
    assert s.trusted_proxies == ("10.0.0.0/8", "::1", "127.0.0.1")
    assert s.allow_insecure_http is False and s.docs_enabled is True
    assert load_settings(env_with(tmp_path, TRUSTED_PROXIES="")).trusted_proxies == ()
    assert load_settings(env_with(tmp_path, PUBLIC_URL="http://192.168.1.10:8000")).public_origin == "http://192.168.1.10:8000"


def test_proxy_mode_requirements(tmp_path):
    base = {"AUTH_MODE": "proxy"}
    with pytest.raises(ConfigError, match="TRUSTED_PROXY_USER_HEADER"):
        load_settings(env_with(tmp_path, **base))
    base["TRUSTED_PROXY_USER_HEADER"] = "Remote-User"
    with pytest.raises(ConfigError, match="TRUSTED_PROXY_SECRET_FILE"):
        load_settings(env_with(tmp_path, **base))
    secret = tmp_path / "proxy-secret"
    secret.write_text(KEY_B, encoding="utf-8")
    base["TRUSTED_PROXY_SECRET_FILE"] = str(secret)
    for wide in ("0.0.0.0/0", "::/0", "10.0.0.0/8,0.0.0.0/0"):
        with pytest.raises(ConfigError, match="refuses TRUSTED_PROXIES"):
            load_settings(env_with(tmp_path, TRUSTED_PROXIES=wide, **base))
    with pytest.raises(ConfigError, match="needs TRUSTED_PROXIES"):
        load_settings(env_with(tmp_path, TRUSTED_PROXIES="", **base))
    s = load_settings(env_with(tmp_path, **base))
    assert s.auth_mode == "proxy" and s.trusted_proxy_secret == KEY_B and s.warnings == ()
    # tailscale serve cannot add a header: allowed with a warning
    optional = {k: v for k, v in base.items() if k != "TRUSTED_PROXY_SECRET_FILE"}
    s = load_settings(env_with(tmp_path, TRUSTED_PROXY_SECRET_OPTIONAL="true", **optional))
    assert any("without TRUSTED_PROXY_SECRET" in w for w in s.warnings)


def test_warnings(tmp_path):
    s = load_settings(
        env_with(
            tmp_path,
            AUTH_MODE="none",
            ALLOWED_HOSTS="kidney.example.org",
            PASSWORD_MIN_LENGTH="12",
            FORWARDED_ALLOW_IPS="*",
            TRUSTED_PROXIES="0.0.0.0/0",
            SESSION_IDLE_DAYS="20",
            SESSION_MAX_DAYS="10",
        )
    )
    text = "\n".join(s.warnings)
    for fragment in ("AUTH_MODE=none", "NIST", "FORWARDED_ALLOW_IPS is ignored", "every client can set X-Forwarded-For", "SESSION_IDLE_DAYS"):
        assert fragment in text, fragment
    assert any("'*'" in w for w in load_settings(env_with(tmp_path, ALLOWED_HOSTS="*")).warnings)


def test_create_app_logs_warnings_and_validates_directly_built_settings(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, password_min_length=10)
    with caplog.at_level(logging.WARNING), TestClient(create_app(settings)):
        pass
    assert "NIST" in caplog.text
    with pytest.raises(ConfigError, match="AUTH_MODE=proxy needs"):
        create_app(Settings(data_dir=tmp_path / "d2", foods_json=foods_json, auth_mode="proxy"))


def test_invalid_env_lock_fails_at_startup(tmp_path, foods_json, monkeypatch):
    monkeypatch.setenv("REGISTRATION_MODE", "everyone")
    with pytest.raises(ConfigError, match="REGISTRATION_MODE"):
        create_app(Settings(data_dir=tmp_path / "data", foods_json=foods_json))


def test_uvicorn_import_exits_cleanly_on_a_config_error(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.endswith("_FILE")}
    env.update(DATA_DIR=str(tmp_path / "data"), AUTH_MODE="ldap", PYTHONPATH=str(REPO))
    proc = subprocess.run([sys.executable, "-c", "import app.main"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "configuration error: AUTH_MODE must be one of" in proc.stderr
    assert "Traceback" not in proc.stderr


# --------------------------------------------------------------------------- #
# SECRET_KEY
# --------------------------------------------------------------------------- #


def test_secret_key_lines_comments_and_blanks(tmp_path):
    f = tmp_path / "key"
    f.write_text(f"# rotated 2026-10-05\n{KEY_B}\n\n  {KEY_A}  \n", encoding="utf-8")
    s = load_settings(env_with(tmp_path, SECRET_KEY_FILE=str(f)))
    assert s.secret_key_lines() == [KEY_B, KEY_A]
    ring = crypto.load_keyring(s)
    assert ring.source == "file" and len(ring.ids) == 2 and ring.current_id == ring.ids[0]


def test_auto_secret_key_file_is_created_0600_and_never_overwritten(tmp_path, caplog):
    s = load_settings(env_with(tmp_path))
    with caplog.at_level(logging.WARNING, logger="kidney_health.crypto"):
        ring = crypto.load_keyring(s)
    path = tmp_path / "data" / "secret.key"
    assert ring.source == "auto" and ring.path == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_text()
    assert len(content.strip()) >= 32
    assert "Back up" in caplog.text and "SECRET_KEY_FILE" in caplog.text
    again = crypto.load_keyring(s)
    assert path.read_text() == content and again.current_id == ring.current_id
    token, _ = ring.seal(purpose="secret:usda", owner=None, fields={"api_key": "k" * 20})
    assert again.unseal(token, purpose="secret:usda", owner=None) == {"api_key": "k" * 20}


def test_startup_creates_the_key_on_the_data_volume(settings):
    with TestClient(create_app(settings)) as c:
        assert c.app.state.keyring.source == "auto"
    assert (settings.data_dir / "secret.key").exists()


def test_env_secret_key_is_used_and_no_file_is_written(tmp_path, foods_json):
    s = load_settings(env_with(tmp_path, SECRET_KEY=KEY_A, FOODS_JSON=str(foods_json)))
    with TestClient(create_app(s)) as c:
        assert c.app.state.keyring.source == "env"
    assert not (tmp_path / "data" / "secret.key").exists()


def test_broken_auto_key_file_is_a_clear_error(tmp_path):
    path = tmp_path / "data" / "secret.key"
    path.parent.mkdir(parents=True)
    path.write_text("short\n")
    with pytest.raises(ConfigError, match="at least 32 characters"):
        crypto.load_keyring(load_settings(env_with(tmp_path)))


def test_rotation_with_two_lines(tmp_path):
    old = crypto.Keyring([KEY_A])
    token, key_id = old.seal(purpose="secret:usda", owner=7, fields={"api_key": "x" * 24})
    assert key_id == old.current_id
    both = crypto.Keyring([KEY_B, KEY_A])  # new first line, old kept for decryption
    assert both.unseal(token, purpose="secret:usda", owner=7)["api_key"] == "x" * 24
    assert both.key_id_of(token) == old.current_id != both.current_id
    rotated = both.rotate(token)
    new_only = crypto.Keyring([KEY_B])
    assert new_only.unseal(rotated, purpose="secret:usda", owner=7)["api_key"] == "x" * 24
    with pytest.raises(crypto.InvalidToken):
        old.unseal(rotated, purpose="secret:usda", owner=7)
    with pytest.raises(crypto.InvalidToken):
        new_only.unseal(token, purpose="secret:usda", owner=7)


def test_config_module_documents_every_key():
    doc = config.__doc__ or ""
    for key in (
        "ALLOWED_HOSTS", "PUBLIC_URL", "TRUSTED_PROXIES", "TRUSTED_PROXY_USER_HEADER", "TRUSTED_PROXY_SECRET",
        "SECRET_KEY", "ALLOW_INSECURE_HTTP", "AUTH_MODE", "ENABLE_API_DOCS", "MAX_BODY_BYTES", "MAX_IMAGE_BYTES",
        "HSTS_MAX_AGE", "PWA_ENABLED", "LOG_LEVEL",
    ):
        assert key in doc, key
