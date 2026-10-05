"""Org lifecycle, membership and invitation facts. The welcome seeders are consumers of
:class:`OrganizationCreated`.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class OrgEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "organizations"
    icon: ClassVar[PhosphorIcon] = "buildings"


@dataclass(frozen=True, kw_only=True)
class OrganizationCreated(OrgEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class OrganizationRenamed(OrgEvent, EntityUpdated):
    """``entity_id`` is the org, so it shows in the org's entity filter; ``label`` the new
    name."""

    verb: ClassVar[str] = "renamed"


@dataclass(frozen=True, kw_only=True)
class OrgHandleChanged(OrgEvent, EntityUpdated):
    """Every ``/{handle}/…`` URL changes. ``label`` is the new handle."""

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
    # entity_name: the invitee's email; no account yet, so no entity_id


@dataclass(frozen=True, kw_only=True)
class InvitationRevoked(OrgEvent):
    verb: ClassVar[str] = "invitation_revoked"
    # entity_id: the revoked invitation
