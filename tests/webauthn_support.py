"""A software passkey for the tests: a CBOR writer and an authenticator that makes and uses passkeys (design note 18 §7).

It writes exactly what a browser and a platform authenticator send, so each check of ``app.auth.webauthn`` can be broken one at a
time: change a flag, the origin, the RP ID, the counter or a byte of the signature.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from app.auth.webauthn import FLAG_AT, FLAG_BE, FLAG_BS, FLAG_UP, FLAG_UV, b64url

RP_ID = "testserver"
ORIGIN = "http://testserver"


def cbor(value: Any) -> bytes:
    """RFC 8949 canonical encoding of ints, bytes, str, lists, dicts, bools and None."""
    def head(major: int, arg: int) -> bytes:
        if arg < 24:
            return bytes([major << 5 | arg])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if arg < 1 << (8 * size):
                return bytes([major << 5 | info]) + arg.to_bytes(size, "big")
        raise ValueError("too big")

    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, (bytes, bytearray)):
        return head(2, len(value)) + bytes(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value))


def client_data(kind: str, challenge: bytes, origin: str = ORIGIN, **extra: Any) -> bytes:
    return json.dumps({"type": kind, "challenge": b64url(challenge), "origin": origin, "crossOrigin": False, **extra},
                      separators=(",", ":")).encode()


@dataclass
class SoftPasskey:
    """One passkey: a private key, its ID, the user handle it was made for and its counter."""

    alg: int = -7
    rp_id: str = RP_ID
    credential_id: bytes = field(default_factory=lambda: os.urandom(16))
    user_handle: bytes = b""
    counter: int = 0
    synced: bool = False

    def __post_init__(self) -> None:
        self.private = ed25519.Ed25519PrivateKey.generate() if self.alg == -8 else ec.generate_private_key(ec.SECP256R1())

    def cose_public_key(self) -> bytes:
        pub = self.private.public_key()
        if self.alg == -8:
            raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            return cbor({1: 1, 3: -8, -1: 6, -2: raw})
        nums = pub.public_numbers()
        return cbor({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def flags(self, uv: bool = True, up: bool = True) -> int:
        return (FLAG_UP if up else 0) | (FLAG_UV if uv else 0) | ((FLAG_BE | FLAG_BS) if self.synced else 0)

    def auth_data(self, *, flags: int, counter: int, attested: bool, rp_id: str | None = None) -> bytes:
        out = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags | (FLAG_AT if attested else 0)])
        out += struct.pack(">I", counter)
        if attested:
            out += b"\0" * 16 + struct.pack(">H", len(self.credential_id)) + self.credential_id + self.cose_public_key()
        return out

    def sign(self, data: bytes) -> bytes:
        if self.alg == -8:
            return self.private.sign(data)
        return self.private.sign(data, ec.ECDSA(hashes.SHA256()))

    def create(self, challenge: bytes, *, origin: str = ORIGIN, uv: bool = True, up: bool = True, rp_id: str | None = None,
               kind: str = "webauthn.create", **client_extra: Any) -> dict[str, bytes]:
        """What ``navigator.credentials.create`` returns, as raw bytes."""
        auth = self.auth_data(flags=self.flags(uv, up), counter=self.counter, attested=True, rp_id=rp_id)
        return {
            "clientDataJSON": client_data(kind, challenge, origin, **client_extra),
            "attestationObject": cbor({"fmt": "none", "attStmt": {}, "authData": auth}),
        }

    def get(self, challenge: bytes, *, origin: str = ORIGIN, uv: bool = True, up: bool = True, rp_id: str | None = None,
            kind: str = "webauthn.get", counter_step: int = 1, **client_extra: Any) -> dict[str, bytes]:
        """What ``navigator.credentials.get`` returns, as raw bytes. The counter goes up by ``counter_step`` (0 keeps it)."""
        if self.counter or counter_step:
            self.counter += counter_step
        cdj = client_data(kind, challenge, origin, **client_extra)
        auth = self.auth_data(flags=self.flags(uv, up), counter=self.counter, attested=False, rp_id=rp_id)
        return {"clientDataJSON": cdj, "authenticatorData": auth,
                "signature": self.sign(auth + hashlib.sha256(cdj).digest()), "userHandle": self.user_handle}


def registration_json(passkey: SoftPasskey, raw: dict[str, bytes]) -> dict[str, Any]:
    """The JSON the page posts after ``create`` (``PublicKeyCredential.toJSON()`` shape)."""
    return {"id": b64url(passkey.credential_id), "rawId": b64url(passkey.credential_id), "type": "public-key",
            "response": {"clientDataJSON": b64url(raw["clientDataJSON"]), "attestationObject": b64url(raw["attestationObject"]),
                         "transports": ["internal"]}}


def assertion_json(passkey: SoftPasskey, raw: dict[str, bytes], *, user_handle: bytes | None = None) -> dict[str, Any]:
    handle = raw["userHandle"] if user_handle is None else user_handle
    return {"id": b64url(passkey.credential_id), "rawId": b64url(passkey.credential_id), "type": "public-key",
            "response": {"clientDataJSON": b64url(raw["clientDataJSON"]), "authenticatorData": b64url(raw["authenticatorData"]),
                         "signature": b64url(raw["signature"]), "userHandle": b64url(handle) if handle else None}}
