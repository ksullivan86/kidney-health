"""Secrets at rest (note 07 §4.12): Keyring sealing, write-only credentials, resolution and quotas."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx2
import pytest

import app.foods as foods_module
from app import credentials, crypto, db
from app.config import ConfigError, Settings
from app.credentials import Credential, InvalidCredential, Unavailable
from app.settings_store import SettingsStore, create_settings_tables

KEY_A = "A" * 40
KEY_B = "B" * 40
LONG_KEY = "usda-0123456789-abcdefghij-9xQz"  # 31 characters -> last4 shown
SHORT_KEY = "short-key-12"  # under 20 characters -> no last4


@pytest.fixture
def ring() -> crypto.Keyring:
    return crypto.Keyring([KEY_A])


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)")
    create_settings_tables(c)
    credentials.create_credentials_tables(c)
    c.executemany("INSERT INTO users (id, username) VALUES (?, ?)", [(1, "admin"), (2, "sam"), (3, "kim")])
    c.commit()
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


# --------------------------------------------------------------------------- #
# Keyring
# --------------------------------------------------------------------------- #


def test_seal_round_trip_and_binding(ring):
    token, key_id = ring.seal(purpose="secret:usda", owner=2, fields={"api_key": LONG_KEY})
    assert key_id == ring.current_id and len(key_id) == 8
    assert LONG_KEY.encode() not in token
    assert ring.unseal(token, purpose="secret:usda", owner=2) == {"api_key": LONG_KEY}
    assert ring.unseal(token.decode(), purpose="secret:usda", owner=2) == {"api_key": LONG_KEY}
    with pytest.raises(crypto.InvalidToken):
        ring.unseal(token, purpose="secret:usda", owner=3)  # copied into another person's row
    with pytest.raises(crypto.InvalidToken):
        ring.unseal(token, purpose="secret:usda", owner=None)  # copied into the shared row
    with pytest.raises(crypto.InvalidToken):
        ring.unseal(token, purpose="ai_provider:1", owner=2)  # copied to another purpose
    tampered = token[:-5] + (b"A" if token[-5:-4] != b"A" else b"B") + token[-4:]
    with pytest.raises(crypto.InvalidToken):
        ring.unseal(tampered, purpose="secret:usda", owner=2)
    with pytest.raises(crypto.InvalidToken):
        crypto.Keyring([KEY_B]).unseal(token, purpose="secret:usda", owner=2)
    with pytest.raises(ValueError):
        ring.seal(purpose="", owner=None, fields={})


def test_key_ids_are_stable_and_not_secret():
    a1, a2, b = crypto.Keyring([KEY_A]), crypto.Keyring([KEY_A]), crypto.Keyring([KEY_B])
    assert a1.ids == a2.ids and a1.current_id != b.current_id
    assert KEY_A not in repr(a1) and "AAAA" not in repr(a1)
    both = crypto.Keyring([KEY_B, KEY_A])
    assert both.ids == [b.current_id, a1.current_id]


def test_subkeys_are_separate_from_the_secrets_key(ring):
    k1 = ring.subkey("kidney-health/v1/login-failures")
    k2 = ring.subkey("kidney-health/v1/device")
    assert len(k1) == 32 and k1 != k2
    assert ring.mac("kidney-health/v1/login-failures", "sam") == ring.mac("kidney-health/v1/login-failures", "sam")
    assert ring.mac("kidney-health/v1/login-failures", "sam") != crypto.Keyring([KEY_B]).mac("kidney-health/v1/login-failures", "sam")
    with pytest.raises(ValueError):
        ring.subkey("kidney-health/v1/secrets")
    # subkeys always come from the current (first) line
    assert crypto.Keyring([KEY_A, KEY_B]).subkey("x/y") == ring.subkey("x/y")


def test_short_or_missing_key_lines_are_refused():
    with pytest.raises(ConfigError):
        crypto.Keyring(["too-short"])
    with pytest.raises(ConfigError):
        crypto.Keyring(["# comment only", ""])


def test_secret_key_file_creation_is_exclusive(tmp_path):
    path = tmp_path / "secret.key"
    lines = crypto.create_secret_key_file(path)
    assert path.read_text().strip() == lines[0]
    with pytest.raises(FileExistsError):
        crypto.create_secret_key_file(path)


# --------------------------------------------------------------------------- #
# Write-only storage
# --------------------------------------------------------------------------- #


def test_store_and_status_are_write_only(conn, ring):
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2, updated_by=2)
    credentials.store_secret(conn, ring, "usda", {"api_key": SHORT_KEY}, owner_user_id=None, updated_by=1)
    own = credentials.secret_status(conn, ring, "usda", owner_user_id=2)
    assert own["set"] is True and own["last4"] == "9xQz" and own["updated_at"]
    shared = credentials.secret_status(conn, ring, "usda", owner_user_id=None)
    assert shared["set"] is True and "last4" not in shared  # under 20 characters: no hint
    assert credentials.secret_status(conn, ring, "usda", owner_user_id=3) == {"set": False}
    dump = "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM secrets"))
    assert LONG_KEY not in dump and SHORT_KEY not in dump
    assert json.dumps(own).find(LONG_KEY) == -1
    # replacing keeps one row per owner
    credentials.store_secret(conn, ring, "usda", {"api_key": "replacement-key-000000000"}, owner_user_id=2)
    assert conn.execute("SELECT COUNT(*) FROM secrets WHERE owner_user_id = 2").fetchone()[0] == 1
    assert credentials.load_secret(conn, ring, "usda", owner_user_id=2) == {"api_key": "replacement-key-000000000"}
    assert credentials.delete_secret(conn, "usda", owner_user_id=2) is True
    assert credentials.delete_secret(conn, "usda", owner_user_id=2) is False


def test_unreadable_and_moved_rows(conn, ring):
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2)
    other = crypto.Keyring([KEY_B])
    assert credentials.secret_status(conn, other, "usda", owner_user_id=2)["status"] == "unreadable"
    # someone with write access copies Sam's ciphertext into Kim's row
    token = conn.execute("SELECT ciphertext FROM secrets WHERE owner_user_id = 2").fetchone()[0]
    now = db.utcnow()
    conn.execute(
        "INSERT INTO secrets (scope, owner_user_id, provider, ciphertext, key_id, created_at, updated_at) VALUES ('user', 3, 'usda', ?, 'x', ?, ?)",
        (token, now, now),
    )
    assert credentials.secret_status(conn, ring, "usda", owner_user_id=3)["status"] == "unreadable"
    with pytest.raises(crypto.InvalidToken):
        credentials.load_secret(conn, ring, "usda", owner_user_id=3)


@pytest.mark.parametrize("bad", ["short", "x" * 513, "has space inside", "tab\there-12345", "nön-ascii-key", ""])
def test_api_key_validation(conn, ring, bad):
    with pytest.raises(InvalidCredential) as info:
        credentials.store_secret(conn, ring, "usda", {"api_key": bad}, owner_user_id=2)
    if bad:
        assert bad not in str(info.value)


def test_unknown_fields_and_providers(conn, ring):
    with pytest.raises(InvalidCredential):
        credentials.store_secret(conn, ring, "usda", {"token": LONG_KEY}, owner_user_id=2)
    with pytest.raises(KeyError):
        credentials.store_secret(conn, ring, "nope", {"api_key": LONG_KEY}, owner_user_id=2)


def test_shared_status_env_key_is_locked(conn, ring, tmp_path):
    env_settings = Settings(data_dir=tmp_path, usda_api_key="ENVKEY-123456789012345")
    assert credentials.shared_status(conn, ring, env_settings, "usda") == {"set": True, "source": "env", "locked": True}
    plain = Settings(data_dir=tmp_path)
    assert credentials.shared_status(conn, ring, plain, "usda") == {"set": False}
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=None)
    status = credentials.shared_status(conn, ring, plain, "usda")
    assert status["source"] == "db" and status["locked"] is False and status["last4"] == "9xQz"


# --------------------------------------------------------------------------- #
# Resolution: own -> shared (allowed, within quota) -> none
# --------------------------------------------------------------------------- #


def resolve(conn, ring, settings, user_id=2, store=None, **kwargs):
    return credentials.resolve(conn, ring, settings, user_id=user_id, provider="usda", store=store or SettingsStore(env={}), **kwargs)


def test_own_key_wins_and_is_counted_without_limit(conn, ring, settings):
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2)
    credentials.store_secret(conn, ring, "usda", {"api_key": "shared-key-0000000000000"}, owner_user_id=None)
    cred = resolve(conn, ring, settings)
    assert isinstance(cred, Credential) and cred.scope == "own" and cred.api_key == LONG_KEY
    assert LONG_KEY not in repr(cred)
    assert credentials.used_today(conn, 2, "usda", "own") == 1


def test_shared_key_with_quota(conn, ring, settings):
    store = SettingsStore(env={})
    credentials.store_secret(conn, ring, "usda", {"api_key": "shared-key-0000000000000"}, owner_user_id=None)
    store.set_instance(conn, "providers.usda.daily_limit_per_user", 2)
    results = [resolve(conn, ring, settings, store=store) for _ in range(3)]
    assert [getattr(r, "scope", None) for r in results[:2]] == ["shared", "shared"]
    assert results[2] == Unavailable("usda", "quota_exhausted")
    assert credentials.used_today(conn, 2, "usda") == 2
    assert isinstance(resolve(conn, ring, settings, user_id=3, store=store), Credential)  # per person
    # tomorrow is a new day
    assert isinstance(resolve(conn, ring, settings, store=store, day="2999-01-01"), Credential)
    store.set_instance(conn, "providers.usda.daily_limit_per_user", 0)  # 0 = unlimited
    assert isinstance(resolve(conn, ring, settings, store=store), Credential)


def test_env_shared_key_and_reasons(conn, ring, tmp_path):
    store = SettingsStore(env={})
    plain = Settings(data_dir=tmp_path)
    assert resolve(conn, ring, plain, store=store) == Unavailable("usda", "not_configured")
    env_settings = Settings(data_dir=tmp_path, usda_api_key="ENVKEY-123456789012345")
    cred = resolve(conn, ring, env_settings, store=store)
    assert cred.scope == "shared" and cred.source == "env" and cred.api_key == "ENVKEY-123456789012345"
    assert resolve(conn, ring, env_settings, store=store, can_use_shared=False) == Unavailable("usda", "not_allowed")
    store.set_instance(conn, "providers.usda.shared_enabled", False)
    assert resolve(conn, ring, env_settings, store=store) == Unavailable("usda", "not_allowed")


def test_own_keys_can_be_disallowed(conn, ring, settings):
    store = SettingsStore(env={})
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2)
    credentials.store_secret(conn, ring, "usda", {"api_key": "shared-key-0000000000000"}, owner_user_id=None)
    store.set_instance(conn, "providers.usda.user_keys_allowed", False)
    assert resolve(conn, ring, settings, store=store).scope == "shared"


def test_unreadable_own_key_never_falls_back_to_shared(conn, ring, settings):
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2)
    credentials.store_secret(conn, ring, "usda", {"api_key": "shared-key-0000000000000"}, owner_user_id=None)
    rotated_away = crypto.Keyring([KEY_B])
    credentials.store_secret(conn, rotated_away, "usda", {"api_key": "shared-key-1111111111111"}, owner_user_id=None)
    assert resolve(conn, rotated_away, settings) == Unavailable("usda", "own_key_unreadable")


def test_quota_take_is_atomic_at_the_limit(conn):
    assert credentials.take_quota(conn, 2, "usda", "shared", 1, day="2026-10-05") is True
    assert credentials.take_quota(conn, 2, "usda", "shared", 1, day="2026-10-05") is False
    row = conn.execute("SELECT requests FROM usage_daily WHERE user_id = 2").fetchone()
    assert row[0] == 1


def test_resolve_before_schema_v3_uses_the_env_key(tmp_path):
    conn = db.connect(":memory:")
    db.migrate(conn)
    ring = crypto.Keyring([KEY_A])
    s = Settings(data_dir=tmp_path, usda_api_key="ENVKEY-123456789012345")
    cred = credentials.resolve(conn, ring, s, user_id=1, provider="usda", store=SettingsStore(env={}))
    assert cred.scope == "shared" and cred.api_key == "ENVKEY-123456789012345"
    conn.close()


def test_usda_key_check_uses_the_header_and_maps_results(monkeypatch):
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        key = request.headers.get("x-api-key")
        if key == "good-key-12345":
            return httpx2.Response(200, json={"foods": []})
        if key == "down-key-12345":
            raise httpx2.ConnectError("boom", request=request)
        return httpx2.Response(403, json={"error": {"code": "API_KEY_INVALID"}})

    monkeypatch.setattr(foods_module, "usda_client", lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    provider = credentials.get_provider("usda")
    assert provider.tester({"api_key": "good-key-12345"}) == "ok"
    assert provider.tester({"api_key": "bad-key-123456"}) == "rejected"
    assert provider.tester({"api_key": "down-key-12345"}) == "unreachable"
    assert all("key" not in str(r.url).lower() for r in seen)
    assert seen[0].url.params["pageSize"] == "1"


def test_credentials_tables_cascade_with_users(conn, ring):
    credentials.store_secret(conn, ring, "usda", {"api_key": LONG_KEY}, owner_user_id=2)
    credentials.take_quota(conn, 2, "usda", "own", 0)
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM usage_daily").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):  # shared rows have no owner, user rows must have one
        conn.execute(
            "INSERT INTO secrets (scope, owner_user_id, provider, ciphertext, key_id, created_at, updated_at) VALUES ('shared', 1, 'usda', x'00', 'k', 'n', 'n')"
        )
