"""The passkey checks in ``app.auth.webauthn`` (design note 18 §3 and §7): the W3C vectors, then each check one at a time."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.auth import webauthn as w
from tests.webauthn_support import ORIGIN, RP_ID, SoftPasskey, cbor

VECTORS = json.loads((Path(__file__).parent / "data" / "webauthn_w3c_vectors.json").read_text())
h = bytes.fromhex


def _register(v: dict, *, require_uv: bool) -> w.Registered:
    r = v["registration"]
    return w.verify_registration(client_data_json=h(r["clientDataJSON"]), attestation_object=h(r["attestationObject"]),
                                 challenge=h(r["challenge"]), origins=VECTORS["origin"], rp_id=VECTORS["rp_id"], require_uv=require_uv)


def _authenticate(v: dict, public_key: bytes, *, require_uv: bool) -> w.Asserted:
    a = v["authentication"]
    return w.verify_authentication(client_data_json=h(a["clientDataJSON"]), authenticator_data=h(a["authenticatorData"]),
                                   signature=h(a["signature"]), challenge=h(a["challenge"]), origins=VECTORS["origin"],
                                   rp_id=VECTORS["rp_id"], public_key=public_key, stored_sign_count=0, require_uv=require_uv)


def _vector_key(v: dict) -> bytes:
    auth = w.parse_authenticator_data(w.cbor_decode(h(v["registration"]["attestationObject"]))["authData"])
    assert auth.public_key is not None
    return auth.public_key


@pytest.mark.parametrize("name", sorted(n for n, v in VECTORS["vectors"].items() if v["expect"] == "accepted"))
def test_w3c_vectors_register_and_sign_in(name: str) -> None:
    v = VECTORS["vectors"][name]
    reg = _register(v, require_uv=False)
    assert reg.credential_id == h(v["registration"]["credential_id"])
    assert reg.alg in w.ALGORITHMS
    assert _authenticate(v, reg.public_key, require_uv=False).counter_went_back is False


@pytest.mark.parametrize("name", sorted(VECTORS["vectors"]))
def test_w3c_vectors_need_user_verification(name: str) -> None:
    v = VECTORS["vectors"][name]
    if v["expect"] != "accepted":
        pytest.skip("refused for another reason")
    for step, verified in v["user_verified"].items():
        if step == "registration":
            run = lambda: _register(v, require_uv=True)  # noqa: E731
        else:
            run = lambda: _authenticate(v, _vector_key(v), require_uv=True)  # noqa: E731
        if verified:
            run()
        else:
            with pytest.raises(w.WebAuthnError, match="fingerprint, face or PIN"):
                run()


@pytest.mark.parametrize("name", ["none-es256-crossOrigin", "none-es256-topOrigin"])
def test_w3c_vectors_inside_another_site_are_refused(name: str) -> None:
    v = VECTORS["vectors"][name]
    with pytest.raises(w.WebAuthnError, match="another site"):
        _register(v, require_uv=False)
    with pytest.raises(w.WebAuthnError, match="another site"):
        _authenticate(v, _vector_key(v), require_uv=False)


def test_all_five_algorithms_are_in_the_vectors() -> None:
    algs = {_register(v, require_uv=False).alg for v in VECTORS["vectors"].values() if v["expect"] == "accepted"}
    assert algs == set(w.ALGORITHMS)


def test_long_credential_id_is_accepted_up_to_1023_bytes() -> None:
    assert len(_register(VECTORS["vectors"]["none-es256-long-credential-id"], require_uv=False).credential_id) == 1023


# --------------------------------------------------------------------------- #
# The software passkey: each check one at a time
# --------------------------------------------------------------------------- #

CHALLENGE = os.urandom(32)


def _reg(pk: SoftPasskey, raw: dict, challenge: bytes = CHALLENGE, origins=ORIGIN, rp_id: str = RP_ID) -> w.Registered:
    return w.verify_registration(client_data_json=raw["clientDataJSON"], attestation_object=raw["attestationObject"],
                                 challenge=challenge, origins=origins, rp_id=rp_id)


def _get(raw: dict, reg: w.Registered, stored: int = 0, challenge: bytes = CHALLENGE, rp_id: str = RP_ID) -> w.Asserted:
    return w.verify_authentication(client_data_json=raw["clientDataJSON"], authenticator_data=raw["authenticatorData"],
                                   signature=raw["signature"], challenge=challenge, origins=(ORIGIN,), rp_id=rp_id,
                                   public_key=reg.public_key, stored_sign_count=stored)


@pytest.mark.parametrize("alg", [-7, -8])
def test_soft_passkey_round_trip(alg: int) -> None:
    pk = SoftPasskey(alg=alg, synced=True)
    reg = _reg(pk, pk.create(CHALLENGE))
    assert (reg.credential_id, reg.alg, reg.backed_up) == (pk.credential_id, alg, True)
    out = _get(pk.get(CHALLENGE), reg, stored=reg.sign_count)
    assert (out.sign_count, out.counter_went_back, out.backed_up) == (1, False, True)


@pytest.mark.parametrize("change, match", [
    ({"challenge": os.urandom(32)}, "challenge does not match"),
    ({"origin": "https://evil.example"}, "different web address"),
    ({"kind": "webauthn.get"}, "different step"),
    ({"uv": False}, "fingerprint, face or PIN"),
    ({"up": False}, "a person was there"),
    ({"rp_id": "other.example"}, "different server"),
    ({"crossOrigin": True}, "another site"),
    ({"topOrigin": "https://evil.example"}, "another site"),
])
def test_registration_checks(change: dict, match: str) -> None:
    pk = SoftPasskey()
    challenge = change.pop("challenge", CHALLENGE)
    raw = pk.create(challenge, **change)
    with pytest.raises(w.WebAuthnError, match=match):
        _reg(pk, raw)


@pytest.mark.parametrize("change, match", [
    ({"origin": "https://evil.example"}, "different web address"),
    ({"kind": "webauthn.create"}, "different step"),
    ({"uv": False}, "fingerprint, face or PIN"),
    ({"up": False}, "a person was there"),
    ({"rp_id": "other.example"}, "different server"),
    ({"crossOrigin": True}, "another site"),
])
def test_sign_in_checks(change: dict, match: str) -> None:
    pk = SoftPasskey()
    reg = _reg(pk, pk.create(CHALLENGE))
    with pytest.raises(w.WebAuthnError, match=match):
        _get(pk.get(CHALLENGE, **change), reg)


def test_sign_in_wrong_challenge_and_bad_signature() -> None:
    pk = SoftPasskey()
    reg = _reg(pk, pk.create(CHALLENGE))
    with pytest.raises(w.WebAuthnError, match="challenge"):
        _get(pk.get(os.urandom(32)), reg)
    raw = pk.get(CHALLENGE)
    raw["signature"] = raw["signature"][:-1] + bytes([raw["signature"][-1] ^ 1])
    with pytest.raises(w.WebAuthnError, match="signature"):
        _get(raw, reg)
    other = SoftPasskey()
    with pytest.raises(w.WebAuthnError, match="signature"):
        _get(other.get(CHALLENGE), reg)


def test_counter_that_does_not_go_up_is_reported() -> None:
    pk = SoftPasskey()
    reg = _reg(pk, pk.create(CHALLENGE))
    assert not _get(pk.get(CHALLENGE), reg, stored=0).counter_went_back
    assert _get(pk.get(CHALLENGE, counter_step=0), reg, stored=pk.counter).counter_went_back
    assert _get(pk.get(CHALLENGE), reg, stored=pk.counter + 5).counter_went_back
    zero = SoftPasskey()  # a passkey that never counts (iCloud Keychain sends 0)
    reg0 = _reg(zero, zero.create(CHALLENGE))
    assert not _get(zero.get(CHALLENGE, counter_step=0), reg0, stored=0).counter_went_back


def test_several_origins_can_be_accepted() -> None:
    pk = SoftPasskey()
    _reg(pk, pk.create(CHALLENGE, origin="https://food.example"), origins=("https://food.example", ORIGIN))


def test_attestation_object_must_have_auth_data_and_a_key() -> None:
    pk = SoftPasskey()
    raw = pk.create(CHALLENGE)
    with pytest.raises(w.WebAuthnError, match="attestation"):
        _reg(pk, {**raw, "attestationObject": cbor({"fmt": "none", "attStmt": {}})})
    no_key = pk.auth_data(flags=pk.flags(), counter=0, attested=False)
    with pytest.raises(w.WebAuthnError, match="did not send a new passkey"):
        _reg(pk, {**raw, "attestationObject": cbor({"fmt": "none", "attStmt": {}, "authData": no_key})})


# --------------------------------------------------------------------------- #
# CBOR, authenticator data and COSE keys
# --------------------------------------------------------------------------- #


def test_cbor_reads_what_webauthn_uses() -> None:
    value = {"fmt": "none", 1: -7, -2: b"\x01\x02", "l": [1, True, False, None], "big": 2 ** 40}
    assert w.cbor_decode(cbor(value)) == value


@pytest.mark.parametrize("raw, match", [
    (b"", "cut short"),
    (b"\x42\x01", "cut short"),
    (b"\x5f\x41\x01\xff", "CBOR form"),          # indefinite-length bytes
    (b"\xf9\x3c\x00", "CBOR form"),              # half float
    (b"\xc1\x00", "CBOR form"),                  # a tag
    (b"\xa2\x01\x01\x01\x02", "repeated"),
    (b"\xa1\x41\x00\x01", "map key"),
    (b"\x63\xff\xfe\xfd", "UTF-8"),
    (b"\x01\x02", "extra bytes"),
    (b"\x9b" + b"\xff" * 8, "cut short"),        # a huge array length
    (b"\x81" * 40 + b"\x00", "nested"),
])
def test_cbor_refuses_what_it_does_not_read(raw: bytes, match: str) -> None:
    with pytest.raises(w.WebAuthnError, match=match):
        w.cbor_decode(raw)


def test_authenticator_data_layout_errors() -> None:
    pk = SoftPasskey()
    good = pk.auth_data(flags=pk.flags(), counter=7, attested=True)
    assert w.parse_authenticator_data(good).sign_count == 7
    with pytest.raises(w.WebAuthnError, match="too short"):
        w.parse_authenticator_data(good[:36])
    with pytest.raises(w.WebAuthnError, match="extra bytes"):
        w.parse_authenticator_data(good + b"\0")
    with pytest.raises(w.WebAuthnError, match="cut short"):
        w.parse_authenticator_data(good[:60])
    bs_without_be = bytearray(good)
    bs_without_be[32] |= w.FLAG_BS
    with pytest.raises(w.WebAuthnError, match="backup eligible"):
        w.parse_authenticator_data(bytes(bs_without_be))
    long_id = SoftPasskey(credential_id=b"x" * 1024)
    with pytest.raises(w.WebAuthnError, match="too long"):
        w.parse_authenticator_data(long_id.auth_data(flags=long_id.flags(), counter=0, attested=True))


@pytest.mark.parametrize("key, match", [
    ({1: 2, 3: -7, -1: 2, -2: b"\0" * 32, -3: b"\0" * 32}, "EC2"),           # wrong curve for ES256
    ({1: 2, 3: -7, -1: 1, -2: b"\0" * 31, -3: b"\0" * 32}, "EC2"),
    ({1: 2, 3: -7, -1: 1, -2: b"\0" * 32, -3: b"\0" * 32}, "not valid"),     # not a point on the curve
    ({1: 3, 3: -257, -1: b"\x01" * 128, -2: b"\x01\x00\x01"}, "2048"),
    ({1: 1, 3: -8, -1: 4, -2: b"\0" * 32}, "Ed25519"),                     # X25519 is not a signing key
    ({1: 2, 3: -9}, "does not support"),
    ([1, 2], "COSE"),
])
def test_cose_keys_that_are_refused(key, match: str) -> None:
    with pytest.raises(w.WebAuthnError, match=match):
        w.cose_key(cbor(key))


def test_base64url_is_strict() -> None:
    assert w.b64url_decode(w.b64url(b"\xff\xfe")) == b"\xff\xfe"
    for bad in ("a+b", "a/b", "ab==", 3):
        with pytest.raises(w.WebAuthnError):
            w.b64url_decode(bad)  # type: ignore[arg-type]
