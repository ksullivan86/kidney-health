"""scripts/asc_ci_certs.py: the TestFlight workflow removes the development certificates its runners make (build 10 failed on
2026-11-26 because the leftovers filled the account). These checks need no network and no Apple account."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("asc_ci_certs", ROOT / "scripts" / "asc_ci_certs.py")
asc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asc)


def cert(cid, ctype, serial, name="", display=""):
    return {"id": cid, "attributes": {"certificateType": ctype, "serialNumber": serial, "name": name, "displayName": display}}


CERTS = [
    cert("a", "DEVELOPMENT", "0A1B", "Apple Development: Created via API", "Created via API"),
    cert("b", "IOS_DEVELOPMENT", "77", "iOS Development: Created via API", "Created via API"),
    cert("c", "DEVELOPMENT", "C0FFEE", "Apple Development: Pat Example", "Pat Example"),  # made in Xcode on a person's Mac
    cert("d", "DISTRIBUTION", "D1", "Apple Distribution: Created via API", "Created via API"),  # never touched
]


def test_old_runs_removes_only_development_certificates_made_through_the_api():
    assert [c["id"] for c in asc.pick(CERTS, "old-runs", set())] == ["a", "b"]


def test_this_run_removes_only_the_development_certificates_on_this_mac():
    assert [c["id"] for c in asc.pick(CERTS, "this-run", {"A1B"})] == ["a"]  # serials compare without leading zeros
    assert [c["id"] for c in asc.pick(CERTS, "this-run", {"C0FFEE"})] == ["c"]  # its key is on this fresh Mac: this run made it
    assert asc.pick(CERTS, "this-run", {"D1"}) == []  # a distribution certificate never
    assert asc.pick(CERTS, "this-run", set()) == []


def test_der_signatures_become_64_bytes():
    r, s = b"\x00" + b"\x81" * 32, b"\x01\x02"
    der = b"\x30" + bytes([4 + len(r) + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
    raw = asc.der_to_raw(der)
    assert raw == b"\x81" * 32 + b"\x00" * 30 + b"\x01\x02"
    with pytest.raises(ValueError):
        asc.der_to_raw(b"\x31\x06\x02\x01\x01\x02\x01\x01")


def test_the_token_verifies_with_the_key(tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        jwt = asc.token("KEYID", "issuer-1", str(path), now=1_700_000_000)
    except FileNotFoundError:
        pytest.skip("no openssl command")
    except subprocess.CalledProcessError:
        pytest.skip("openssl cannot sign here")
    import base64
    import json

    head, body, sig = jwt.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(pad(head)) == {"alg": "ES256", "kid": "KEYID", "typ": "JWT"}
    claims = json.loads(pad(body))
    assert claims == {"iss": "issuer-1", "iat": 1_700_000_000, "exp": 1_700_000_600, "aud": "appstoreconnect-v1"}
    raw = pad(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))


def test_the_script_uses_only_the_standard_library_and_apples_host():
    text = (ROOT / "scripts" / "asc_ci_certs.py").read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in text.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "base64", "json", "os", "re", "subprocess", "sys", "tempfile", "time", "urllib"}
    assert asc.API == "https://api.appstoreconnect.apple.com/v1"
