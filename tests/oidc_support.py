"""A fake OpenID Connect provider for the tests (design note 24 §5): discovery, a JWKS, a token endpoint that checks the code,
the redirect URI, PKCE and the client secret, and ID tokens signed with real RSA, EC and Ed25519 keys.

No network: :func:`attach` points the app's :class:`app.auth.oidc.OidcClient` at :meth:`FakeProvider.handler` through the same
SSRF-checked transport the app uses (a fake resolver gives every name a public address, or the address a test chooses), so the
address checks run in every test.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.config import OidcEnv

ISSUER = "https://idp.example.org/application/o/kidney/"
CLIENT_ID = "kidney-health-test"
CLIENT_SECRET = "fake-client-secret-0123456789abcdef"
PUBLIC_ADDRESS = "93.184.216.34"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_b64(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_of(key: Any, kid: str, alg: str | None = None) -> dict[str, Any]:
    pub = key.public_key()
    if isinstance(pub, rsa.RSAPublicKey):
        n = pub.public_numbers()
        out: dict[str, Any] = {"kty": "RSA", "n": _int_b64(n.n), "e": _int_b64(n.e)}
    elif isinstance(pub, ec.EllipticCurvePublicKey):
        n = pub.public_numbers()
        size = (pub.curve.key_size + 7) // 8
        out = {"kty": "EC", "crv": {256: "P-256", 384: "P-384"}[pub.curve.key_size],
               "x": b64(n.x.to_bytes(size, "big")), "y": b64(n.y.to_bytes(size, "big"))}
    else:
        raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        out = {"kty": "OKP", "crv": "Ed25519", "x": b64(raw)}
    out.update(kid=kid, use="sig")
    if alg:
        out["alg"] = alg
    return out


def sign(header: dict[str, Any], claims: dict[str, Any], key: Any) -> str:
    head = b64(json.dumps(header).encode())
    body = b64(json.dumps(claims).encode())
    data = f"{head}.{body}".encode()
    alg = header.get("alg")
    if alg == "none":
        sig = b""
    elif alg == "HS256":
        import hmac

        sig = hmac.new(key, data, hashlib.sha256).digest()
    elif alg.startswith("RS"):
        sig = key.sign(data, padding.PKCS1v15(), {"256": hashes.SHA256(), "384": hashes.SHA384(), "512": hashes.SHA512()}[alg[2:]])
    elif alg.startswith("PS"):
        h = {"256": hashes.SHA256(), "384": hashes.SHA384(), "512": hashes.SHA512()}[alg[2:]]
        sig = key.sign(data, padding.PSS(mgf=padding.MGF1(h), salt_length=h.digest_size), h)
    elif alg.startswith("ES"):
        h, size = {"ES256": (hashes.SHA256(), 32), "ES384": (hashes.SHA384(), 48)}[alg]
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(h)))
        sig = r.to_bytes(size, "big") + s.to_bytes(size, "big")
    elif alg == "EdDSA":
        sig = key.sign(data)
    else:
        raise ValueError(alg)
    return f"{head}.{body}.{b64(sig)}"


@dataclass
class Grant:
    nonce: str
    challenge: str
    redirect_uri: str
    token: str | None = None  # a token chosen by the test, sent as is
    claims: dict[str, Any] = field(default_factory=dict)
    header: dict[str, Any] = field(default_factory=dict)
    key: Any = None


class FakeProvider:
    def __init__(self, issuer: str = ISSUER, client_id: str = CLIENT_ID, client_secret: str | None = CLIENT_SECRET) -> None:
        self.issuer, self.client_id, self.client_secret = issuer, client_id, client_secret
        base = issuer.rstrip("/")
        self.base = base
        self.rsa = rsa_key()
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.ed = ed25519.Ed25519PrivateKey.generate()
        self.keys: list[tuple[str, Any, str]] = [("rsa1", self.rsa, "RS256"), ("ec1", self.ec, "ES256"), ("ed1", self.ed, "EdDSA")]
        self.discovery_extra: dict[str, Any] = {}
        self.grants: dict[str, Grant] = {}
        self.calls: list[str] = []  # the paths asked, in order
        self.token_forms: list[dict[str, list[str]]] = []
        self.token_headers: list[dict[str, str]] = []
        self.address = PUBLIC_ADDRESS

    # ------------------------------------------------------------------ wiring
    def discovery(self) -> dict[str, Any]:
        doc = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.base}/authorize",
            "token_endpoint": f"{self.base}/token",
            "jwks_uri": f"{self.base}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256", "ES256", "EdDSA"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        }
        doc.update(self.discovery_extra)
        return doc

    def jwks(self) -> dict[str, Any]:
        return {"keys": [jwk_of(key, kid, alg) for kid, key, alg in self.keys]}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.calls.append(path)
        if path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(200, json=self.discovery())
        if path.endswith("/jwks"):
            return httpx2.Response(200, json=self.jwks())
        if path.endswith("/token") and request.method == "POST":
            return self._token(request)
        return httpx2.Response(404, json={"error": "not_found"})

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = parse_qs(request.content.decode())
        self.token_forms.append(form)
        self.token_headers.append(dict(request.headers))
        one = {k: v[0] for k, v in form.items()}
        if self.client_secret is not None:
            expected = "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            if request.headers.get("authorization") != expected and one.get("client_secret") != self.client_secret:
                return httpx2.Response(401, json={"error": "invalid_client"})
        grant = self.grants.pop(one.get("code", ""), None)
        if grant is None or one.get("grant_type") != "authorization_code":
            return httpx2.Response(400, json={"error": "invalid_grant"})
        if one.get("redirect_uri") != grant.redirect_uri:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        verifier = one.get("code_verifier", "")
        if b64(hashlib.sha256(verifier.encode()).digest()) != grant.challenge:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        token = grant.token or self.id_token(grant.nonce, grant.claims, grant.header, grant.key)
        return httpx2.Response(200, json={"access_token": "access-token-never-stored", "refresh_token": "refresh-token-never-stored",
                                          "token_type": "Bearer", "expires_in": 300, "id_token": token})

    # ------------------------------------------------------------------ tokens
    def id_token(self, nonce: str, claims: dict[str, Any] | None = None, header: dict[str, Any] | None = None, key: Any = None,
                 kid: str = "rsa1") -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": self.client_id, "sub": "subject-1", "iat": now, "exp": now + 300, "nonce": nonce,
                "auth_time": now, "email": "mum@example.org", "email_verified": True, "name": "Mum"}
        body.update(claims or {})
        body = {k: v for k, v in body.items() if v is not ...}  # a test drops a claim with ...
        found = {k: (key_, alg) for k, key_, alg in self.keys}
        alg = (header or {}).get("alg") or found.get(kid, (None, "RS256"))[1]
        head = {"alg": alg, "kid": kid, "typ": "JWT"}
        head.update(header or {})
        head = {k: v for k, v in head.items() if v is not ...}
        signer = key if key is not None else found.get(kid, (self.rsa, alg))[0]
        return sign(head, body, signer)

    def authorize(self, location: str, *, claims: dict[str, Any] | None = None, header: dict[str, Any] | None = None,
                  key: Any = None, token: str | None = None) -> tuple[str, str, dict[str, str]]:
        """What the provider's page does: read the authorization request and make a code. ``(code, state, query)``."""
        parts = urlsplit(location)
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{self.base}/authorize", location
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert query["response_type"] == "code" and query["client_id"] == self.client_id
        assert query["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.grants[code] = Grant(query["nonce"], query["code_challenge"], query["redirect_uri"], token, dict(claims or {}),
                                  dict(header or {}), key)
        return code, query["state"], query


def env(**changes: Any) -> OidcEnv:
    values: dict[str, Any] = dict(enabled=True, issuer=ISSUER, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    values.update(changes)
    return OidcEnv(**values)


def attach(app: Any, provider: FakeProvider) -> FakeProvider:
    oc = app.state.oidc
    oc.resolver = lambda host, port: [provider.address]
    oc.direct = httpx2.MockTransport(provider.handler)
    oc.use_env_proxy = False
    return provider


def sign_in_with_provider(client: Any, provider: FakeProvider, **authorize: Any) -> httpx2.Response:
    """Press the button, sign in at the provider, come back. The callback's answer (a 303)."""
    r = client.get("/api/auth/oidc/start", follow_redirects=False)
    assert r.status_code == 303, r.text
    code, state, _ = provider.authorize(r.headers["location"], **authorize)
    return client.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)


def come_back(client: Any, provider: FakeProvider, url: str, **authorize: Any) -> httpx2.Response:
    """Follow a ``{url}`` from a link, re-auth or invite start to the provider and back."""
    code, state, _ = provider.authorize(url, **authorize)
    return client.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
