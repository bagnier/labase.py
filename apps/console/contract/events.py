"""Console's business events — platform-admin actions on the shared trail.

Granting/revoking the platform-admin role and setting per-org overrides are ``settings.*`` events
(the vocabulary the trail already uses). None is CRUD, so they subclass
:class:`~apps.shared.events.BusinessEvent` directly and spell out a ``verb`` of their own.
``AdminGranted``/``AdminRevoked`` are server-wide (no ``org_id``), the override events carry the
target org.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, OrgScoped


class SettingsEvent(BusinessEvent):
    app_name: ClassVar[str] = "settings"
    icon: ClassVar[str] = "gear"


@dataclass(frozen=True, kw_only=True)
class AdminGranted(SettingsEvent):
    verb: ClassVar[str] = "admin_granted"
    # the promoted user: entity_id resolved from the email, entity_name = the email


@dataclass(frozen=True, kw_only=True)
class AdminRevoked(SettingsEvent):
    verb: ClassVar[str] = "admin_revoked"
    # the demoted user: entity_id resolved from the email, entity_name = the email


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
