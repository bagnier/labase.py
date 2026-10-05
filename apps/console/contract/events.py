"""The console's ``settings.*`` events: admin grants and revokes (server-wide), per-org
overrides (carrying their org).
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class SettingsEvent(BusinessEvent):
    app_name: ClassVar[AppName] = "settings"
    icon: ClassVar[PhosphorIcon] = "gear"


@dataclass(frozen=True, kw_only=True)
class AdminGranted(SettingsEvent):
    verb: ClassVar[str] = "admin_granted"
    # entity_id, entity_name: the promoted user and their email


@dataclass(frozen=True, kw_only=True)
class AdminRevoked(SettingsEvent):
    verb: ClassVar[str] = "admin_revoked"
    # entity_id, entity_name: the demoted user and their email


@dataclass(frozen=True, kw_only=True)
class OrgOverrideSet(OrgScoped, SettingsEvent):
    verb: ClassVar[str] = "org_override_set"
    app: str
    key: str
    value: str


@dataclass(frozen=True, kw_only=True)
class OrgOverrideRemoved(OrgScoped, SettingsEvent):
    verb: ClassVar[str] = "org_override_removed"
    app: str
    key: str
