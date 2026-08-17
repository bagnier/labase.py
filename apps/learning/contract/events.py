"""Learning's business events — a review recorded on the shared journal.

Reviewing a card advances its schedule, so :class:`CardReviewed` derives from
:class:`~apps.shared.events.EntityUpdated` (``kind`` → ``"learning.reviewed"``) and carries the
review outcome; the router emits it on the request's session, scoped by actor/org.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityUpdated, OrgScoped


class LearningEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[str] = "learning"
    icon: ClassVar[str] = "book-open"


@dataclass(frozen=True, kw_only=True)
class CardReviewed(LearningEvent, EntityUpdated):
    verb: ClassVar[str] = "reviewed"
    outcome: str
