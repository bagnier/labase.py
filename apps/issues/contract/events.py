"""The facts this context owns — what happened to an issue, never what was logged about one.

A captured exception is not one of these: it is a technical sighting the drain folds into an
occurrence. What reaches the journal is the issue's *lifecycle* — it opened, it came back on a
later release, an admin triaged it. The first two are the tracker's own verdicts, server-wide, so
``user_id``/``org_id`` stay ``None`` (console-only rows); ``IssueStatusChanged`` carries the
acting admin. Alerting is one consumer of these facts, not their purpose.
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
