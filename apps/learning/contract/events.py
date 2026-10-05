"""``learning.reviewed``: a card reviewed, with its outcome."""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class LearningEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "learning"
    icon: ClassVar[PhosphorIcon] = "book-open"


@dataclass(frozen=True, kw_only=True)
class CardReviewed(LearningEvent, EntityUpdated):
    verb: ClassVar[str] = "reviewed"
    outcome: str
