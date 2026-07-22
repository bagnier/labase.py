"""Console's business events — platform-admin actions on the shared trail.

Granting/revoking the platform-admin role and setting per-org overrides are ``settings.*`` events
(the vocabulary the trail already uses); admin-role changes are ``warning``-level. They subclass
:class:`~apps.shared.events.BusinessEvent` directly with an explicit ``kind``; the persister on
the base records them. ``AdminGranted``/``AdminRevoked`` are server-wide (``org_id`` = ``None``),
the override events carry the target org.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent


class SettingsEvent(BusinessEvent):
    entity: ClassVar[str] = "settings"
    icon: ClassVar[str] = "gear"


@dataclass(frozen=True, kw_only=True)
class AdminGranted(SettingsEvent):
    kind: ClassVar[str] = "settings.admin_granted"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class AdminRevoked(SettingsEvent):
    kind: ClassVar[str] = "settings.admin_revoked"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class LastAdminViolationBlocked(SettingsEvent):
    kind: ClassVar[str] = "settings.last_admin_violation"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class OrgOverrideSet(SettingsEvent):
    kind: ClassVar[str] = "settings.org_override_set"
    app: str | None = None
    key: str | None = None
    value: str | None = None


@dataclass(frozen=True, kw_only=True)
class OrgOverrideRemoved(SettingsEvent):
    kind: ClassVar[str] = "settings.org_override_removed"
    app: str | None = None
    key: str | None = None
