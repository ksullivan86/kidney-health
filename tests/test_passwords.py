"""Password hashing and the NIST SP 800-63B-4 policy (note 07 §4.6, §9 N9)."""
from __future__ import annotations

import threading
import unicodedata

import pytest

from app.auth import passwords, policy


@pytest.fixture(autouse=True)
def argon2_scheme():
    passwords.configure("argon2id")
    yield
    passwords.configure("argon2id")


def test_argon2id_hash_verify_and_parameters():
    stored = passwords.hash_password("correct horse battery staple")
    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert passwords.verify_password("correct horse battery staple", stored)
    assert not passwords.verify_password("correct horse battery stapl", stored)
    assert not passwords.verify_password("correct horse battery staple ", stored)  # never truncated or trimmed
    assert passwords.hash_password("correct horse battery staple") != stored  # salted
    assert not passwords.needs_rehash(stored)


def test_nfc_normalisation_makes_composed_and_decomposed_equal():
    composed = "café au lait on sunday mornings"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    stored = passwords.hash_password(composed)
    assert passwords.verify_password(decomposed, stored)


def test_needs_rehash_for_other_parameters_and_schemes():
    assert passwords.needs_rehash("$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaA")
    assert passwords.needs_rehash(None)
    passwords.configure("scrypt")
    scrypt_hash = passwords.hash_password("a long enough passphrase here")
    assert scrypt_hash.startswith("$scrypt$ln=14,r=8,p=5$")
    assert not passwords.needs_rehash(scrypt_hash)
    passwords.configure("argon2id")
    assert passwords.needs_rehash(scrypt_hash)  # upgraded at the next successful sign-in
    assert passwords.verify_password("a long enough passphrase here", scrypt_hash)  # still verifies
    assert not passwords.verify_password("wrong", scrypt_hash)


def test_malformed_or_missing_hashes_never_verify():
    for stored in (None, "", "plaintext", "$argon2id$garbage", "$scrypt$ln=99,r=8,p=1$AAAA$AAAA", "$scrypt$broken"):
        assert passwords.verify_password("anything at all", stored) is False


def test_dummy_hash_is_a_real_hash_of_a_random_secret():
    dummy = passwords.dummy_hash()
    assert dummy.startswith("$argon2id$") and dummy == passwords.dummy_hash()
    assert not passwords.verify_password("not-a-real-password-used-for-timing", dummy)


def test_self_test_passes_and_reports_a_missing_backend(monkeypatch):
    passwords.self_test()
    from cryptography.exceptions import UnsupportedAlgorithm

    def broken(_password: str) -> str:
        raise UnsupportedAlgorithm("no argon2")

    monkeypatch.setattr(passwords, "_hash_unlocked", broken)
    with pytest.raises(passwords.PasswordBackendUnavailable, match="PASSWORD_HASH=scrypt"):
        passwords.self_test()


def test_hashing_is_gated_to_two_at_a_time(monkeypatch):
    monkeypatch.setattr(passwords, "GATE_TIMEOUT_S", 0.05)
    held = [passwords._GATE.acquire(), passwords._GATE.acquire()]
    try:
        assert all(held)
        with pytest.raises(passwords.HashBusy):
            passwords.hash_password("x" * 20)
        with pytest.raises(passwords.HashBusy):
            passwords.verify_password("x", passwords.dummy_hash())
    finally:
        passwords._GATE.release()
        passwords._GATE.release()
    assert passwords.verify_password("x" * 20, passwords.hash_password("x" * 20))


def test_concurrent_hashing_never_exceeds_the_gate():
    peak = 0
    active = 0
    lock = threading.Lock()
    original = passwords._hash_unlocked

    def counting(password: str) -> str:
        nonlocal peak, active
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            return original(password)
        finally:
            with lock:
                active -= 1

    passwords._hash_unlocked = counting  # type: ignore[assignment]
    try:
        threads = [threading.Thread(target=passwords.hash_password, args=(f"password number {i}",)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        passwords._hash_unlocked = original  # type: ignore[assignment]
    assert 1 <= peak <= passwords.GATE_SLOTS


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #


def test_length_counts_code_points_14_15_128_129():
    assert policy.validate_new_password("a" * 13 + "bc") == []  # 15, not a single repeated character
    assert policy.validate_new_password("abcdx" * 2 + "pqrs") == [policy.MSG_TOO_SHORT.format(n=15)]  # 14
    assert policy.validate_new_password("é" * 14)[0].startswith("Use at least 15")
    long_ok = ("plum orbit candle " * 8)[:128]
    assert len(long_ok) == 128 and policy.validate_new_password(long_ok) == []
    assert policy.validate_new_password(long_ok + "x") == [policy.MSG_TOO_LONG]
    # emoji are one code point each
    assert policy.validate_new_password("🍌" * 14 + "x") == []


def test_min_length_is_configurable():
    assert policy.validate_new_password("orbitcandle", min_length=8) == []
    assert policy.validate_new_password("orbitcan", min_length=10)[0].startswith("Use at least 10")


def test_blocklist_compares_the_whole_password_casefolded():
    assert "password1" in policy.blocklist() and len(policy.blocklist()) == 10_000
    assert policy.validate_new_password("Password1", min_length=8) == [policy.MSG_COMMON]
    assert policy.validate_new_password("PASSWORD1", min_length=8) == [policy.MSG_COMMON]
    # a blocklisted word inside a longer password is fine (NIST: whole password, not substrings)
    assert policy.validate_new_password("password1 is not my password", min_length=8) == []


def test_context_words_are_refused():
    assert policy.validate_new_password("sam.the.gardener", username="sam.the.gardener") == [policy.MSG_CONTEXT]
    assert policy.validate_new_password("Margaret Thompson", display_name="margaret thompson") == [policy.MSG_CONTEXT]
    assert policy.validate_new_password("Kidney-Health", min_length=8) == [policy.MSG_CONTEXT]
    assert policy.validate_new_password("kidney health", min_length=8) == [policy.MSG_CONTEXT]
    assert policy.validate_new_password("Our Family Server", instance_name="our family server") == [policy.MSG_CONTEXT]


def test_repeated_characters_and_straight_runs_are_refused():
    for weak in ("aaaaaaaaaaaaaaaa", "123456789012345", "qwertyuiopasdfg", "abcdefghijklmnop", "zyxwvutsrqponmlk", "1qaz2wsx3edc4rfv"):
        assert policy.MSG_PATTERN in policy.validate_new_password(weak), weak
    assert policy.validate_new_password("plum orbit candle 73") == []


def test_breach_check_is_opt_in_and_fails_open(monkeypatch):
    calls = []

    def fake_breached(password: str) -> bool:
        calls.append(password)
        return True

    monkeypatch.setattr(policy, "breached", fake_breached)
    assert policy.validate_new_password("plum orbit candle 73") == []
    assert calls == []
    assert policy.validate_new_password("plum orbit candle 73", breach_check=True) == [policy.MSG_BREACHED]


def test_breached_uses_k_anonymity_and_ignores_network_errors(monkeypatch):
    import hashlib

    import httpx2

    digest = hashlib.sha1(b"hunter2 hunter2 hunter2").hexdigest().upper()
    seen = []

    class FakeClient:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            seen.append(url)
            body = f"{digest[5:]}:42\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0\n"
            return httpx2.Response(200, text=body)

    monkeypatch.setattr(httpx2, "Client", FakeClient)
    assert policy.breached("hunter2 hunter2 hunter2") is True
    assert seen[1] == policy.HIBP_URL + digest[:5]  # only the first five hex digits leave the server
    assert seen[0]["headers"]["Add-Padding"] == "true"

    class Down(FakeClient):
        def get(self, url):
            raise httpx2.ConnectError("offline")

    monkeypatch.setattr(httpx2, "Client", Down)
    assert policy.breached("hunter2 hunter2 hunter2") is False
