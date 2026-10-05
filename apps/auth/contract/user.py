import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuthenticatedUser:
    id: uuid.UUID
    email: str
    access_token: str = ""
    is_admin: bool = False
    claims: Mapping[str, Any] = field(default_factory=dict)
    # With an org API key: the principal is the key's creator, limited to this organization.
    api_key_org_id: uuid.UUID | None = None
