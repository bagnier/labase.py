"""Software WebAuthn authenticator for the passkey E2E scenarios.

GoTrue validates the origin *inside the signed clientDataJSON* against its
configured ``rp_origins`` — and this device signs whatever origin we claim.
That is what lets both drivers run the real server-side ceremony (app →
GoTrue → auth schema) even though the browser E2E server lives on a random
port GoTrue would reject, and the API driver has no browser at all. The
browser-visible affordances (buttons, sections) are asserted separately.

Self-contained on ``cryptography`` (P-256 / ES256, "none" attestation, minimal
CBOR): the off-the-shelf soft authenticators pin a vulnerable ``cryptography``
range, which pip-audit rightly rejects.
"""

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hashes import SHA256

# Must be listed in supabase/config.toml [auth.webauthn] rp_origins.
RP_ORIGIN = "http://localhost:8000"

_AAGUID = bytes(16)
_FLAG_UP = 0x01
_FLAG_AT = 0x40


def _to_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _to_b64url(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return str(value).rstrip("=")


def _cbor_head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 256:
        return bytes([(major << 5) | 24, n])
    return bytes([(major << 5) | 25]) + n.to_bytes(2, "big")


def _cbor(value: Any) -> bytes:
    """Minimal canonical CBOR — just the shapes an attestation object needs."""
    if isinstance(value, int):
        return _cbor_head(0, value) if value >= 0 else _cbor_head(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode()
        return _cbor_head(3, len(encoded)) + encoded
    if isinstance(value, dict):  # caller supplies keys in canonical order
        return _cbor_head(5, len(value)) + b"".join(_cbor(k) + _cbor(v) for k, v in value.items())
    raise TypeError(f"unsupported CBOR type: {type(value)!r}")


def _client_data(kind: str, challenge_b64url: str) -> bytes:
    return json.dumps(
        {"type": kind, "challenge": challenge_b64url.rstrip("="), "origin": RP_ORIGIN},
        separators=(",", ":"),
    ).encode()


class PasskeyDevice:
    """One resident P-256 credential, reused between registration and sign-in."""

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._credential_id = os.urandom(32)
        self._rp_id = ""
        self._user_handle = b""
        self._sign_count = 0

    def _cose_key(self) -> bytes:
        numbers = self._key.public_key().public_numbers()
        # EC2 / ES256 COSE key; keys already in canonical order.
        return _cbor(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def create_credential(self, registration: dict[str, Any]) -> dict[str, Any]:
        """Answer GoTrue's registration options with a "none" attestation."""
        options = registration["options"]
        pk = options.get("publicKey", options)
        self._rp_id = pk["rp"]["id"]
        self._user_handle = _to_bytes(pk["user"]["id"])
        client_data = _client_data("webauthn.create", pk["challenge"])
        auth_data = (
            hashlib.sha256(self._rp_id.encode()).digest()
            + bytes([_FLAG_UP | _FLAG_AT])
            + self._sign_count.to_bytes(4, "big")
            + _AAGUID
            + len(self._credential_id).to_bytes(2, "big")
            + self._credential_id
            + self._cose_key()
        )
        attestation = _cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": _to_b64url(self._credential_id),
            "rawId": _to_b64url(self._credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _to_b64url(client_data),
                "attestationObject": _to_b64url(attestation),
            },
        }

    def get_assertion(self, authentication: dict[str, Any]) -> dict[str, Any]:
        """Answer GoTrue's authentication options with a signed assertion."""
        options = authentication["options"]
        pk = options.get("publicKey", options)
        rp_id = pk.get("rpId") or self._rp_id
        client_data = _client_data("webauthn.get", pk["challenge"])
        self._sign_count += 1
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([_FLAG_UP])
            + self._sign_count.to_bytes(4, "big")
        )
        signature = self._key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(SHA256())
        )
        return {
            "id": _to_b64url(self._credential_id),
            "rawId": _to_b64url(self._credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _to_b64url(client_data),
                "authenticatorData": _to_b64url(auth_data),
                "signature": _to_b64url(signature),
                "userHandle": _to_b64url(self._user_handle),
            },
        }
