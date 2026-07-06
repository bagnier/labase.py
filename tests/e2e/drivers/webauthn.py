"""Software WebAuthn authenticator for the passkey E2E scenarios.

GoTrue validates the origin *inside the signed clientDataJSON* against its
configured ``rp_origins`` — and this device signs whatever origin we claim.
That is what lets both drivers run the real server-side ceremony (app →
GoTrue → auth schema) even though the browser E2E server lives on a random
port GoTrue would reject, and the API driver has no browser at all. The
browser-visible affordances (buttons, sections) are asserted separately.
"""

import base64
from typing import Any

from soft_webauthn import SoftWebauthnDevice

# Must be listed in supabase/config.toml [auth.webauthn] rp_origins.
RP_ORIGIN = "http://localhost:8000"


def _to_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _to_b64url(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return str(value).rstrip("=")


class PasskeyDevice:
    """One resident credential, reused between registration and sign-in."""

    def __init__(self) -> None:
        self._device = SoftWebauthnDevice()

    def create_credential(self, registration: dict[str, Any]) -> dict[str, Any]:
        """Answer GoTrue's registration options with an attestation credential."""
        options = registration["options"]
        pk = options.get("publicKey", options)
        att = self._device.create(
            {
                "publicKey": {
                    **pk,
                    "challenge": _to_bytes(pk["challenge"]),
                    "user": {**pk["user"], "id": _to_bytes(pk["user"]["id"])},
                }
            },
            RP_ORIGIN,
        )
        return {
            "id": _to_b64url(att["id"]),
            "rawId": _to_b64url(att["rawId"]),
            "type": att["type"],
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _to_b64url(att["response"]["clientDataJSON"]),
                "attestationObject": _to_b64url(att["response"]["attestationObject"]),
            },
        }

    def get_assertion(self, authentication: dict[str, Any]) -> dict[str, Any]:
        """Answer GoTrue's authentication options with a signed assertion."""
        options = authentication["options"]
        pk = options.get("publicKey", options)
        assertion = self._device.get(
            {"publicKey": {**pk, "challenge": _to_bytes(pk["challenge"])}}, RP_ORIGIN
        )
        return {
            "id": _to_b64url(assertion["id"]),
            "rawId": _to_b64url(assertion["rawId"]),
            "type": assertion["type"],
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _to_b64url(assertion["response"]["clientDataJSON"]),
                "authenticatorData": _to_b64url(assertion["response"]["authenticatorData"]),
                "signature": _to_b64url(assertion["response"]["signature"]),
                "userHandle": _to_b64url(assertion["response"]["userHandle"] or b""),
            },
        }
