"""Org's public events — org lifecycle, membership and invitations on the shared trail.

All are :class:`OrgEvent` business events (org-scoped) — an org being created, a member
joining/leaving, roles changing, invitations. A refused action is *not* here: a blocked
last-owner change or a non-owner reaching an owner-only route changed nothing, so it is a
structured log line, not a trail row.

:class:`OrganizationCreated` doubles as the welcome-seeding trigger: each per-app seeder is a
durable ``bus.on`` consumer of it, run by the listener off the trail after the org commits. One
event, one business meaning — no separate seeding signal.
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
