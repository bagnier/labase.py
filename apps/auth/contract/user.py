import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    access_token: str = ""
    is_admin: bool = False
    claims: Mapping[str, Any] = field(default_factory=dict)
    # Set when the request authenticated with an org API key: the principal is the
    # key's creator (RLS applies as them), pinned to this single organisation.
    api_key_org_id: uuid.UUID | None = None
