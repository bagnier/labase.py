"""Org's public events — org lifecycle, membership and invitations on the shared trail.

All are :class:`OrgEvent` business events (org-scoped) — an org being created, a member
joining/leaving, roles changing, invitations, and the ``warning``-level guard rejections;
the persister on the :class:`~apps.shared.events.BusinessEvent` base records every one.

:class:`OrganizationCreated` doubles as the welcome-seeding trigger: the per-app seeders
subscribe to it directly, so emitting it dispatches to them (by concrete type) and then to
the persister (by base type). One event, one business meaning — no separate seeding signal.
"""

import uuid
from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityUpdated


class OrgEvent(BusinessEvent):
    entity: ClassVar[str] = "organizations"
    icon: ClassVar[str] = "buildings"


@dataclass(frozen=True, kw_only=True)
class OrganizationCreated(OrgEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class OrganizationRenamed(OrgEvent, EntityUpdated):
    """The org's display name changed — ``kind`` → ``"organizations.renamed"``. ``entity_id`` is
    the org id, ``label`` the new name, so it joins the org's rows in the per-entity filter."""

    verb: ClassVar[str] = "renamed"


@dataclass(frozen=True, kw_only=True)
class OrgHandleChanged(OrgEvent, EntityUpdated):
    """The org handle changed — rewrites every ``/{handle}/…`` URL, so it is a sensitive,
    high-visibility change. ``label`` is the new handle."""

    verb: ClassVar[str] = "handle_changed"


@dataclass(frozen=True, kw_only=True)
class MemberJoined(OrgEvent):
    kind: ClassVar[str] = "organizations.member_joined"


@dataclass(frozen=True, kw_only=True)
class MemberLeft(OrgEvent):
    kind: ClassVar[str] = "organizations.member_left"


@dataclass(frozen=True, kw_only=True)
class MemberRoleChanged(OrgEvent):
    kind: ClassVar[str] = "organizations.member_role_changed"
    target_user_id: uuid.UUID | None = None
    role: str | None = None


@dataclass(frozen=True, kw_only=True)
class MemberRemoved(OrgEvent):
    kind: ClassVar[str] = "organizations.member_removed"
    target_user_id: uuid.UUID | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationSent(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_sent"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationRevoked(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_revoked"
    invitation_id: uuid.UUID | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationEmailMismatch(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_email_mismatch"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class LastOwnerViolationBlocked(OrgEvent):
    kind: ClassVar[str] = "organizations.last_owner_violation"
    level: ClassVar[str] = "warning"
    target_user_id: uuid.UUID | None = None


@dataclass(frozen=True, kw_only=True)
class OwnershipViolation(OrgEvent):
    kind: ClassVar[str] = "organizations.ownership_violation"
    level: ClassVar[str] = "warning"
    path: str | None = None
