"""Org's public events — org lifecycle, membership and invitations on the shared trail.

All are :class:`OrgEvent` business events (org-scoped) — an org being created, a member
joining/leaving, roles changing, invitations, and the ``warning``-level guard rejections;
the persister on the :class:`~apps.shared.events.BusinessEvent` base records every one.

:class:`OrganizationCreated` doubles as the welcome-seeding trigger: the per-app seeders
subscribe to it directly, so emitting it dispatches to them (by concrete type) and then to
the persister (by base type). One event, one business meaning — no separate seeding signal.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityUpdated, OrgScoped


class OrgEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[str] = "organizations"
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
    verb: ClassVar[str] = "member_joined"


@dataclass(frozen=True, kw_only=True)
class MemberLeft(OrgEvent):
    verb: ClassVar[str] = "member_left"


@dataclass(frozen=True, kw_only=True)
class MemberRoleChanged(OrgEvent):
    verb: ClassVar[str] = "member_role_changed"
    role: str


@dataclass(frozen=True, kw_only=True)
class MemberRemoved(OrgEvent):
    verb: ClassVar[str] = "member_removed"


@dataclass(frozen=True, kw_only=True)
class InvitationSent(OrgEvent):
    verb: ClassVar[str] = "invitation_sent"
    # the invitee — no account yet, so entity_name = their email, entity_id stays None


@dataclass(frozen=True, kw_only=True)
class InvitationRevoked(OrgEvent):
    verb: ClassVar[str] = "invitation_revoked"
    # the revoked invitation is the subject: its id rides on entity_id


@dataclass(frozen=True, kw_only=True)
class InvitationEmailMismatch(OrgEvent):
    verb: ClassVar[str] = "invitation_email_mismatch"
    # the mismatched invitee email rides in entity_name (no account guaranteed)


@dataclass(frozen=True, kw_only=True)
class LastOwnerViolationBlocked(OrgEvent):
    verb: ClassVar[str] = "last_owner_violation"


@dataclass(frozen=True, kw_only=True)
class OwnershipViolation(OrgEvent):
    verb: ClassVar[str] = "ownership_violation"
    path: str
