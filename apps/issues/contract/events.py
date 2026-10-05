"""An issue's lifecycle facts: opened, regressed (server-wide, no user or org), triaged (by an
admin). A captured exception itself is an occurrence, not a fact.
"""

import uuid
from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityUpdated
from apps.shared.vocabulary import AppName, PhosphorIcon


class IssueEvent(BusinessEvent):
    app_name: ClassVar[AppName] = "issues"
    icon: ClassVar[PhosphorIcon] = "bug-beetle"


@dataclass(frozen=True, kw_only=True)
class IssueSubject:
    """The entity fields made required: an alert must point at an issue. A base, since a
    subclass cannot make a defaulted field required again."""

    entity_id: uuid.UUID
    entity_name: str


@dataclass(frozen=True, kw_only=True)
class IssueOpened(IssueSubject, IssueEvent):
    verb: ClassVar[str] = "opened"


@dataclass(frozen=True, kw_only=True)
class IssueRegressed(IssueSubject, IssueEvent):
    verb: ClassVar[str] = "regressed"
    resolved_in_release: str | None
    seen_version: str


@dataclass(frozen=True, kw_only=True)
class IssueStatusChanged(IssueEvent, EntityUpdated):
    verb: ClassVar[str] = "status_changed"
    status: str
