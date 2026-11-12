"""Web Push for reminders (design note 35; app/webpush.py): RFC 8291 encryption against the RFC's own example, byte for byte;
the VAPID JWT (RFC 8292) and Apple's rules for it; the push-host allowlist; the key file; the sender behind the real checked
transport with a fake push service. Nothing touches the network."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import webpush
from app.config import ConfigError

d = webpush.b64url_decode

# RFC 8291 §5 and Appendix A.
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
AS_PUBLIC = "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
MESSAGE = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6"
           "cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
HEADER = "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
APPLE = "https://web.push.apple.com/QGuQyavXutnMH7GXOkR8VHM7E8Wy1aQiZ3Wj3zZbd0Q"
PUBLIC_IP = "17.188.143.33"


def private(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(d(text), "big"), ec.SECP256R1())


def browser() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    return key, webpush.b64url(webpush.public_bytes(key.public_key())), webpush.b64url(os.urandom(16))


# --------------------------------------------------------------------------- RFC 8291


def test_the_rfc_8291_example_byte_for_byte() -> None:
    assert webpush.b64url(webpush.public_bytes(private(AS_PRIVATE).public_key())) == AS_PUBLIC
    assert webpush.b64url(webpush.public_bytes(private(UA_PRIVATE).public_key())) == UA_PUBLIC
    body = webpush.encrypt(PLAINTEXT, d(UA_PUBLIC), d(AUTH), as_private=private(AS_PRIVATE), salt=d(SALT))
    assert webpush.b64url(body) == MESSAGE
    assert webpush.b64url(body[:86]) == HEADER and webpush.b64url(body[86:]) == CIPHERTEXT
    assert len(body) == 144  # the RFC's Content-Length is 145: its body ends with a line break


def test_the_browser_side_decrypts_the_example_and_a_fresh_message() -> None:
    assert webpush.decrypt(d(MESSAGE), private(UA_PRIVATE), d(AUTH)) == PLAINTEXT
    key, pub, auth = browser()
    text = json.dumps(webpush.message("Food log", "Time to log lunch.", "https://kidney.example.org/#add")).encode()
    first = webpush.encrypt(text, d(pub), d(auth))
    second = webpush.encrypt(text, d(pub), d(auth))
    assert first != second  # a new salt and key every time
    assert webpush.decrypt(first, key, d(auth)) == text and webpush.decrypt(second, key, d(auth)) == text


def test_payloads_stay_under_apples_4_kb() -> None:
    _, pub, auth = browser()
    assert len(webpush.encrypt(b"x" * webpush.MAX_PAYLOAD, d(pub), d(auth))) == 4096
    with pytest.raises(ValueError):
        webpush.encrypt(b"x" * (webpush.MAX_PAYLOAD + 1), d(pub), d(auth))


def test_the_message_is_declarative_web_push() -> None:
    assert webpush.message("Food log", "Time to log lunch.", "https://k.example/#add") == {
        "web_push": 8030, "notification": {"title": "Food log", "body": "Time to log lunch.", "navigate": "https://k.example/#add",
                                           "lang": "en"}}


# --------------------------------------------------------------------------- VAPID


def _verify(jwt: str, public: ec.EllipticCurvePublicKey) -> dict:
    head, body, sig = jwt.split(".")
    raw = d(sig)
    assert len(raw) == 64
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                  f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(d(head)) == {"typ": "JWT", "alg": "ES256"}
    return json.loads(d(body))


def test_the_vapid_jwt_follows_apples_rules() -> None:
    now = [1_800_000_000.0]
    key = ec.generate_private_key(ec.SECP256R1())
    vapid = webpush.Vapid(key, "mailto:admin@example.org", clock=lambda: now[0])
    auth = vapid.authorization(APPLE)
    token = auth.split("t=", 1)[1].split(",", 1)[0]
    assert auth == f"vapid t={token}, k={vapid.public_key}"
    claims = _verify(token, key.public_key())
    assert claims == {"aud": "https://web.push.apple.com", "exp": 1_800_000_000 + 12 * 3600, "sub": "mailto:admin@example.org"}
    assert claims["exp"] - now[0] <= 24 * 3600
    assert d(vapid.public_key)[0] == 4 and len(d(vapid.public_key)) == 65
    # Reused for an hour per push service, then a new one.
    now[0] += 3599
    assert vapid.token("https://web.push.apple.com") == token
    assert vapid.token("https://fcm.googleapis.com") != token
    now[0] += 2
    fresh = vapid.token("https://web.push.apple.com")
    assert fresh != token and _verify(fresh, key.public_key())["exp"] == int(now[0]) + 12 * 3600
    assert "PRIVATE" not in repr(vapid) and vapid.public_key in repr(vapid)


# --------------------------------------------------------------------------- push hosts


@pytest.mark.parametrize("endpoint", [
    APPLE,
    "https://api.push.apple.com/3/device/abc",
    "https://fcm.googleapis.com/fcm/send/dPf1:APA91b",
    "https://fcm.googleapis.com/wp/dPf1",
    "https://updates.push.services.mozilla.com/wpush/v2/gAAAAAB",
    "https://wns2-par02p.notify.windows.com/w/?token=BQYAAA",
    "https://web.push.apple.com:443/x",
])
def test_known_push_services_are_accepted(endpoint: str) -> None:
    assert webpush.check_endpoint(endpoint) == endpoint


@pytest.mark.parametrize("endpoint", [
    "http://web.push.apple.com/x",  # not https
    "https://push.apple.com/x",  # the bare suffix is not a push host
    "https://web.push.apple.com.evil.example/x",
    "https://evilpush.apple.com/x",
    "https://fcm.googleapis.com.evil.example/x",
    "https://storage.googleapis.com/x",  # only the push host of googleapis.com
    "https://web.push.apple.com:8443/x",  # another port
    "https://user@web.push.apple.com/x",
    "https://169.254.169.254/latest/meta-data",
    "https://127.0.0.1/x",
    "https://localhost/x",
    "https://example.org/push",
    "https://web.push.apple.com/x#frag",
    "https://web.push.apple.com/a b",
    "https://web.push.apple.com/" + "a" * 1100,
    "",
    None,
    42,
])
def test_other_endpoints_are_refused(endpoint) -> None:
    assert webpush.check_endpoint(endpoint) is None


def test_keys_must_be_a_p256_point_and_16_bytes() -> None:
    _, pub, auth = browser()
    assert webpush.check_keys(pub, auth) is not None
    assert webpush.check_keys(pub, webpush.b64url(b"x" * 15)) is None
    assert webpush.check_keys(webpush.b64url(b"\x04" + b"\x01" * 64), auth) is None  # not on the curve
    assert webpush.check_keys("not base64!", auth) is None
    assert webpush.check_keys(None, auth) is None


# --------------------------------------------------------------------------- the key file


def test_the_key_is_made_once_with_mode_0600_inside_data_dir(tmp_path: Path) -> None:
    path = tmp_path / "data" / "vapid_private.pem"
    key = webpush.load_or_create_key(path, tmp_path / "data")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = webpush.load_or_create_key(path, tmp_path / "data")
    assert webpush.public_bytes(again.public_key()) == webpush.public_bytes(key.public_key())


def test_a_missing_key_outside_data_dir_and_a_wrong_key_stop_the_start(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        webpush.load_or_create_key(tmp_path / "secrets" / "vapid.pem", tmp_path / "data")
    assert not (tmp_path / "secrets" / "vapid.pem").exists()
    bad = tmp_path / "data" / "bad.pem"
    bad.parent.mkdir()
    bad.write_text("not a key")
    with pytest.raises(ConfigError, match="not a PEM private key"):
        webpush.load_or_create_key(bad, tmp_path / "data")
    from cryptography.hazmat.primitives import serialization

    other = ec.generate_private_key(ec.SECP384R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                    serialization.NoEncryption())
    bad.write_bytes(other)
    with pytest.raises(ConfigError, match="P-256"):
        webpush.load_or_create_key(bad, tmp_path / "data")


# --------------------------------------------------------------------------- sending


class FakePush:
    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.calls: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        return httpx2.Response(self.status, headers={"Location": "https://elsewhere.example/"} if self.status == 302 else {})


def sender(fake: FakePush, address: str = PUBLIC_IP) -> webpush.Sender:
    return webpush.Sender(webpush.Vapid(ec.generate_private_key(ec.SECP256R1()), "mailto:a@example.org"), timeout_s=2,
                          resolver=lambda host, port: [address], direct=httpx2.MockTransport(fake.handler), use_env_proxy=False)


def test_a_send_has_the_headers_and_an_encrypted_body_the_browser_can_read() -> None:
    fake = FakePush()
    push = sender(fake)
    key, pub, auth = browser()
    payload = webpush.message("Food log", "Time to log lunch.", "https://k.example/#add")
    assert push.send(webpush.Target(APPLE, pub, auth), payload) is None
    (req,) = fake.calls
    assert req.method == "POST" and req.headers["host"] == "web.push.apple.com" and req.url.host == PUBLIC_IP
    assert req.headers["ttl"] == "3600" and req.headers["urgency"] == "normal"
    assert req.headers["content-encoding"] == "aes128gcm" and req.headers["user-agent"] == "reminders"
    assert req.headers["authorization"].startswith("vapid t=") and push.public_key in req.headers["authorization"]
    assert json.loads(webpush.decrypt(req.content, key, d(auth))) == payload


@pytest.mark.parametrize(("status", "code"), [(201, None), (202, None), (404, "gone"), (410, "gone"), (403, "auth"),
                                              (429, "busy"), (503, "busy"), (413, "rejected"), (302, "bad_answer")])
def test_push_service_answers_become_short_codes(status: int, code: str | None) -> None:
    fake = FakePush(status)
    _, pub, auth = browser()
    assert sender(fake).send(webpush.Target(APPLE, pub, auth), {"x": 1}) == code
    assert len(fake.calls) == 1  # a redirect is never followed


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"])
def test_private_addresses_are_refused_by_the_checked_transport(address: str) -> None:
    fake = FakePush()
    _, pub, auth = browser()
    assert sender(fake, address).send(webpush.Target(APPLE, pub, auth), {"x": 1}) == "blocked"
    assert fake.calls == []


def test_an_endpoint_off_the_list_is_never_contacted() -> None:
    fake = FakePush()
    _, pub, auth = browser()
    assert sender(fake).send(webpush.Target("https://example.org/push", pub, auth), {"x": 1}) == "blocked"
    assert fake.calls == []


def test_a_slow_push_service_hits_the_deadline() -> None:
    import threading

    gate = threading.Event()

    def slow(request: httpx2.Request) -> httpx2.Response:
        gate.wait(5)
        return httpx2.Response(201)

    push = webpush.Sender(webpush.Vapid(ec.generate_private_key(ec.SECP256R1()), "mailto:a@example.org"), timeout_s=0.2,
                          resolver=lambda h, p: [PUBLIC_IP], direct=httpx2.MockTransport(slow), use_env_proxy=False)
    _, pub, auth = browser()
    try:
        assert push.send(webpush.Target(APPLE, pub, auth), {"x": 1}) == "timeout"
    finally:
        gate.set()
