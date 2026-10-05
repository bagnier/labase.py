"""``api_keys.created`` and ``api_keys.revoked``. ``ApiKeyIssued`` is named apart from the
``ApiKeyCreated`` DTO. Only the key's id and name are carried, never its secret.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class ApiKeyEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "api_keys"
    icon: ClassVar[PhosphorIcon] = "key"


@dataclass(frozen=True, kw_only=True)
class ApiKeyIssued(ApiKeyEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class ApiKeyRevoked(ApiKeyEvent, EntityDeleted):
    verb: ClassVar[str] = "revoked"
