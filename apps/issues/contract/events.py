"""Issues' business events — alerting *and* the journal, one typed vocabulary.

``IssueOpened``/``IssueRegressed`` are the alerting signals (subscribers react without knowing the
emitter); as :class:`~apps.shared.events.BusinessEvent` subclasses they also land on the shared
journal — server-wide, so ``user_id``/``org_id`` stay ``None`` (console-only rows). A human
resolving/reopening an issue is ``IssueStatusChanged``, carrying the acting admin as ``user_id``.
"""

import uuid
from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityUpdated


class IssueEvent(BusinessEvent):
    app_name: ClassVar[str] = "issues"
    icon: ClassVar[str] = "bug-beetle"


@dataclass(frozen=True, kw_only=True)
class IssueSubject:
    """The base's entity slots, narrowed to required: an alert with no issue to point at is
    meaningless. A base rather than a redeclaration per event — overriding a field that carries
    a default cannot express "required again", while inheriting one that never had a default can."""

    entity_id: uuid.UUID
    entity_name: str


@dataclass(frozen=True, kw_only=True)
class IssueOpened(IssueSubject, IssueEvent):
    """A new issue appeared. The issue *is* the subject."""

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
