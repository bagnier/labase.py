"""Pure key-material logic — no framework or persistence imports."""

import hashlib
import secrets
from dataclasses import dataclass

from apps.auth.contract.api_keys import API_KEY_PREFIX


@dataclass(frozen=True)
class NewKey:
    token: str  # the full secret, shown once and never stored
    prefix: str  # displayable head, kept for identification
    key_hash: str  # sha256 hex, the only thing at rest


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_key() -> NewKey:
    token = API_KEY_PREFIX + secrets.token_hex(20)
    return NewKey(token=token, prefix=token[:12], key_hash=hash_token(token))
