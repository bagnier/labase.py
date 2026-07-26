"""Issues' business events — alerting *and* the trail, one typed vocabulary.

``IssueOpened``/``IssueRegressed`` are the alerting signals (subscribers react without knowing the
emitter); as :class:`~apps.shared.events.BusinessEvent` subclasses they also land on the shared
trail — server-wide, so ``user_id``/``org_id`` stay ``None`` (console-only rows). A human
resolving/reopening an issue is ``IssueStatusChanged``, carrying the acting admin as ``user_id``.
"""

import uuid
from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityUpdated


class IssueEvent(BusinessEvent):
    entity: ClassVar[str] = "issues"
    icon: ClassVar[str] = "bug-beetle"


@dataclass(frozen=True, kw_only=True)
class IssueOpened(IssueEvent):
    kind: ClassVar[str] = "issues.opened"
    group_id: uuid.UUID
    title: str


@dataclass(frozen=True, kw_only=True)
class IssueRegressed(IssueEvent):
    kind: ClassVar[str] = "issues.regressed"
    group_id: uuid.UUID
    title: str
    resolved_in_version: str | None
    seen_version: str


@dataclass(frozen=True, kw_only=True)
class IssueStatusChanged(IssueEvent, EntityUpdated):
    verb: ClassVar[str] = "status_changed"
    status: str
