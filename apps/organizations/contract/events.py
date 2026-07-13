"""Org's public events — membership, invitations and org lifecycle on the shared trail.

Two families share this module:

- :class:`OrgCreated` — the internal *signal* emitted when a personal org is auto-seeded (carries
  the owner's ``access_token`` so subscribers can seed a welcome page). It stays a lean signal.
- the :class:`OrgEvent` business events — an org being created, a member joining/leaving, roles
  changing, invitations, and the ``warning``-level guard rejections. All are org-scoped; the
  persister on the :class:`~apps.shared.events.BusinessEvent` base records them.
"""

import uuid
from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityUpdated


@dataclass(frozen=True)
class OrgCreated:
    """Emitted post-commit once a new organisation and its owner exist; subscribers seed without
    importing one another. Not a trail event — a lean integration signal carrying the token."""

    org_id: uuid.UUID
    access_token: str


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
    target_user_id: str | None = None
    role: str | None = None


@dataclass(frozen=True, kw_only=True)
class MemberRemoved(OrgEvent):
    kind: ClassVar[str] = "organizations.member_removed"
    target_user_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationSent(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_sent"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationRevoked(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_revoked"
    invitation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class InvitationEmailMismatch(OrgEvent):
    kind: ClassVar[str] = "organizations.invitation_email_mismatch"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class LastOwnerViolationBlocked(OrgEvent):
    kind: ClassVar[str] = "organizations.last_owner_violation"
    level: ClassVar[str] = "warning"
    target_user_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class OwnershipViolation(OrgEvent):
    kind: ClassVar[str] = "organizations.ownership_violation"
    level: ClassVar[str] = "warning"
    path: str | None = None
