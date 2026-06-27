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
