"""API keys' business events — issuing and revoking recorded on the shared trail.

Issuing is a create, revoking a state change (an update), so they derive from the shared CRUD
abstracts with domain verbs (``"api_keys.created"`` / ``"api_keys.revoked"``). ``ApiKeyIssued`` is
named apart from the ``ApiKeyCreated`` response DTO; the persister records both, scoped by
actor/org. The secret is never carried — only the key id and its name.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted


class ApiKeyEvent(BusinessEvent):
    entity: ClassVar[str] = "api_keys"
    icon: ClassVar[str] = "key"


@dataclass(frozen=True, kw_only=True)
class ApiKeyIssued(ApiKeyEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class ApiKeyRevoked(ApiKeyEvent, EntityDeleted):
    verb: ClassVar[str] = "revoked"
