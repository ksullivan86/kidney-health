"""Passkeys: the Relying Party checks of WebAuthn (design note 18 §3), built on ``cryptography`` only.

Pure functions, no database and no clock: :func:`verify_registration` (WebAuthn L3 §7.1) and :func:`verify_authentication`
(§7.2). The caller supplies the challenge it issued, the accepted origin and the RP ID, and keeps the stored passkey.

What is here:

* a CBOR reader (RFC 8949) for the subset WebAuthn uses: definite lengths, integers, byte and text strings, arrays, maps, and
  the simple values false, true and null. Anything else is refused, as are nesting deeper than 16 and trailing bytes;
* the authenticator data layout (§6.1) and attested credential data (§6.5.1);
* COSE public keys (RFC 9052/9053) for ES256, ES384, ES512 (EC2, P-256/384/521), RS256 (RSA, PKCS #1 v1.5) and EdDSA (Ed25519).

Attestation statements are not checked (note 18 §9.5): the server asks for ``attestation: "none"`` and stores nothing from them.
User verification is required unless a caller passes ``require_uv=False``; only the tests do, because the W3C vectors set the
flags at random. Every failure raises :class:`WebAuthnError` with a short reason in plain words; the sign-in route shows a generic message instead.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

# COSE algorithm numbers (IANA "COSE Algorithms"), in the order the server offers them.
ES256, EDDSA, ES384, ES512, RS256 = -7, -8, -35, -36, -257
ALGORITHMS = (ES256, EDDSA, ES384, ES512, RS256)

FLAG_UP = 0x01  # user present
FLAG_UV = 0x04  # user verified
FLAG_BE = 0x08  # backup eligible
FLAG_BS = 0x10  # backed up
FLAG_AT = 0x40  # attested credential data included
FLAG_ED = 0x80  # extension data included

MAX_CREDENTIAL_ID = 1023  # §5.1.3: at most 1023 bytes
MAX_DEPTH = 16


class WebAuthnError(ValueError):
    """A check failed. ``str(error)`` is a short reason for logs and the person's own screen."""


# --------------------------------------------------------------------------- #
# Encodings
# --------------------------------------------------------------------------- #


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or any(ch in text for ch in "+/=\n\r "):
        raise WebAuthnError("A value is not in base64url.")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise WebAuthnError("A value is not in base64url.") from exc


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------------- #
# CBOR (the subset WebAuthn uses)
# --------------------------------------------------------------------------- #


def _cbor_item(data: bytes, pos: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise WebAuthnError("The passkey data is nested too deeply.")
    if pos >= len(data):
        raise WebAuthnError("The passkey data is cut short.")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise WebAuthnError("The passkey data is cut short.")
        arg = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise WebAuthnError("The passkey data uses a CBOR form this server does not read.")
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise WebAuthnError("The passkey data is cut short.")
        raw = bytes(data[pos:pos + arg])
        pos += arg
        if major == 2:
            return raw, pos
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError as exc:
            raise WebAuthnError("The passkey data has text that is not UTF-8.") from exc
    if major == 4:
        if arg > len(data) - pos:
            raise WebAuthnError("The passkey data is cut short.")
        items = []
        for _ in range(arg):
            item, pos = _cbor_item(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        if arg > len(data) - pos:
            raise WebAuthnError("The passkey data is cut short.")
        out: dict[Any, Any] = {}
        for _ in range(arg):
            key, pos = _cbor_item(data, pos, depth + 1)
            if not isinstance(key, (int, str)):
                raise WebAuthnError("The passkey data has a map key this server does not read.")
            if key in out:
                raise WebAuthnError("The passkey data has a repeated map key.")
            out[key], pos = _cbor_item(data, pos, depth + 1)
        return out, pos
    if major == 7 and info < 24:
        if arg == 20:
            return False, pos
        if arg == 21:
            return True, pos
        if arg == 22:
            return None, pos
    raise WebAuthnError("The passkey data uses a CBOR form this server does not read.")


def cbor_decode_first(data: bytes) -> tuple[Any, int]:
    """The first CBOR item in ``data`` and the offset just after it."""
    return _cbor_item(bytes(data), 0, 0)


def cbor_decode(data: bytes) -> Any:
    """One CBOR item that fills all of ``data``."""
    value, end = cbor_decode_first(data)
    if end != len(data):
        raise WebAuthnError("The passkey data has extra bytes at the end.")
    return value


# --------------------------------------------------------------------------- #
# COSE keys
# --------------------------------------------------------------------------- #

_CURVES = {ES256: (1, ec.SECP256R1(), hashes.SHA256(), 32), ES384: (2, ec.SECP384R1(), hashes.SHA384(), 48),
           ES512: (3, ec.SECP521R1(), hashes.SHA512(), 66)}


@dataclass(frozen=True)
class CoseKey:
    alg: int
    key: Any  # a cryptography public key

    def verify(self, signature: bytes, message: bytes) -> bool:
        try:
            if self.alg in _CURVES:
                self.key.verify(signature, message, ec.ECDSA(_CURVES[self.alg][2]))
            elif self.alg == RS256:
                self.key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
            else:
                self.key.verify(signature, message)
        except (InvalidSignature, ValueError):
            return False
        return True


def cose_key(raw: bytes) -> CoseKey:
    """A public key from its COSE form (RFC 9052 §7, RFC 9053). Only the algorithms of :data:`ALGORITHMS`."""
    value = cbor_decode(raw) if isinstance(raw, (bytes, bytearray)) else raw
    if not isinstance(value, dict):
        raise WebAuthnError("The passkey's public key is not a COSE key.")
    kty, alg = value.get(1), value.get(3)
    if alg not in ALGORITHMS:
        raise WebAuthnError("The passkey uses a key type this server does not support.")
    try:
        if alg in _CURVES:
            crv, curve, _, size = _CURVES[alg]
            x, y = value.get(-2), value.get(-3)
            if kty != 2 or value.get(-1) != crv or not isinstance(x, bytes) or not isinstance(y, bytes) \
                    or len(x) != size or len(y) != size:
                raise WebAuthnError("The passkey's public key is not a valid EC2 key.")
            key: Any = ec.EllipticCurvePublicKey.from_encoded_point(curve, b"\x04" + x + y)
        elif alg == RS256:
            n, e = value.get(-1), value.get(-2)
            if kty != 3 or not isinstance(n, bytes) or not isinstance(e, bytes) or len(n) < 256:
                raise WebAuthnError("The passkey's public key is not a valid RSA key of at least 2048 bits.")
            key = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
        else:
            x = value.get(-2)
            if kty != 1 or value.get(-1) != 6 or not isinstance(x, bytes) or len(x) != 32:
                raise WebAuthnError("The passkey's public key is not a valid Ed25519 key.")
            key = ed25519.Ed25519PublicKey.from_public_bytes(x)
    except WebAuthnError:
        raise
    except (ValueError, TypeError) as exc:
        raise WebAuthnError("The passkey's public key is not valid.") from exc
    return CoseKey(int(alg), key)


# --------------------------------------------------------------------------- #
# Authenticator data (§6.1) and client data (§5.8.1)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuthData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    credential_id: bytes | None = None
    public_key: bytes | None = None  # the COSE key exactly as sent

    @property
    def user_present(self) -> bool:
        return bool(self.flags & FLAG_UP)

    @property
    def user_verified(self) -> bool:
        return bool(self.flags & FLAG_UV)

    @property
    def backed_up(self) -> bool:
        return bool(self.flags & FLAG_BS)


def parse_authenticator_data(data: bytes) -> AuthData:
    data = bytes(data)
    if len(data) < 37:
        raise WebAuthnError("The authenticator data is too short.")
    rp_id_hash, flags = data[:32], data[32]
    (sign_count,) = struct.unpack(">I", data[33:37])
    if flags & FLAG_BS and not flags & FLAG_BE:
        raise WebAuthnError("The authenticator data says backed up but not backup eligible.")
    pos = 37
    credential_id = public_key = None
    if flags & FLAG_AT:
        if len(data) < pos + 18:
            raise WebAuthnError("The attested credential data is cut short.")
        pos += 16  # AAGUID: which model of authenticator; not used (attestation is not checked)
        (length,) = struct.unpack(">H", data[pos:pos + 2])
        pos += 2
        if length > MAX_CREDENTIAL_ID:
            raise WebAuthnError("The passkey's ID is too long.")
        if len(data) < pos + length:
            raise WebAuthnError("The attested credential data is cut short.")
        credential_id = data[pos:pos + length]
        pos += length
        _, end = cbor_decode_first(data[pos:])
        public_key = data[pos:pos + end]
        pos += end
    if flags & FLAG_ED:
        extensions, end = cbor_decode_first(data[pos:])
        if not isinstance(extensions, dict):
            raise WebAuthnError("The authenticator data's extensions are not a map.")
        pos += end
    if pos != len(data):
        raise WebAuthnError("The authenticator data has extra bytes at the end.")
    return AuthData(rp_id_hash, flags, sign_count, credential_id, public_key)


def check_client_data(raw: bytes, *, kind: str, challenge: bytes, origins: tuple[str, ...] | list[str] | str) -> dict[str, Any]:
    """§7.1 steps 5 to 10 and §7.2 steps 10 to 14: the JSON the browser signed."""
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WebAuthnError("The browser's data is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise WebAuthnError("The browser's data is not valid JSON.")
    if data.get("type") != kind:
        raise WebAuthnError("The browser's data is for a different step.")
    sent = data.get("challenge")
    if not isinstance(sent, str) or b64url_decode(sent) != challenge:
        raise WebAuthnError("The challenge does not match. Try again.")
    accepted = (origins,) if isinstance(origins, str) else tuple(origins)
    if data.get("origin") not in accepted:
        raise WebAuthnError("The passkey was used on a different web address.")
    if data.get("crossOrigin") is True or "topOrigin" in data:
        raise WebAuthnError("The passkey was used inside another site's page.")
    return data


def _check_auth_data(auth: AuthData, rp_id: str, require_uv: bool) -> None:
    if auth.rp_id_hash != hashlib.sha256(rp_id.encode("idna")).digest():
        raise WebAuthnError("The passkey is for a different server.")
    if not auth.user_present:
        raise WebAuthnError("The device did not confirm that a person was there.")
    if require_uv and not auth.user_verified:
        raise WebAuthnError("The device did not check a fingerprint, face or PIN.")


# --------------------------------------------------------------------------- #
# Registration (§7.1) and authentication (§7.2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Registered:
    credential_id: bytes
    public_key: bytes  # COSE, as sent
    alg: int
    sign_count: int
    backed_up: bool


def verify_registration(*, client_data_json: bytes, attestation_object: bytes, challenge: bytes,
                        origins: tuple[str, ...] | list[str] | str, rp_id: str, require_uv: bool = True) -> Registered:
    check_client_data(client_data_json, kind="webauthn.create", challenge=challenge, origins=origins)
    attestation = cbor_decode(attestation_object)
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes) \
            or not isinstance(attestation.get("fmt"), str):
        raise WebAuthnError("The passkey's attestation is not in the expected form.")
    auth = parse_authenticator_data(attestation["authData"])
    _check_auth_data(auth, rp_id, require_uv)
    if auth.credential_id is None or auth.public_key is None:
        raise WebAuthnError("The device did not send a new passkey.")
    if not auth.credential_id:
        raise WebAuthnError("The passkey's ID is empty.")
    key = cose_key(auth.public_key)
    return Registered(auth.credential_id, auth.public_key, key.alg, auth.sign_count, auth.backed_up)


@dataclass(frozen=True)
class Asserted:
    sign_count: int
    backed_up: bool
    counter_went_back: bool


def verify_authentication(*, client_data_json: bytes, authenticator_data: bytes, signature: bytes, challenge: bytes,
                          origins: tuple[str, ...] | list[str] | str, rp_id: str, public_key: bytes,
                          stored_sign_count: int, require_uv: bool = True) -> Asserted:
    """Raises on any failed check, except a counter that did not go up: that is returned as ``counter_went_back`` so the caller
    can audit it before refusing."""
    check_client_data(client_data_json, kind="webauthn.get", challenge=challenge, origins=origins)
    auth = parse_authenticator_data(authenticator_data)
    _check_auth_data(auth, rp_id, require_uv)
    key = cose_key(public_key)
    if not key.verify(bytes(signature), bytes(authenticator_data) + hashlib.sha256(bytes(client_data_json)).digest()):
        raise WebAuthnError("The passkey's signature is not right.")
    went_back = (auth.sign_count != 0 or stored_sign_count != 0) and auth.sign_count <= stored_sign_count
    return Asserted(auth.sign_count, auth.backed_up, went_back)
