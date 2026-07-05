import uuid
from datetime import date
from typing import Protocol

from apps.learning.domain.models import CardState, Schedule


class ReviewRepositoryProtocol(Protocol):
    """The persistence surface the review use-case needs — nothing more."""

    async def get_state(self, card_id: uuid.UUID) -> CardState | None: ...

    async def reviews_today(self, today: date) -> int: ...

    async def apply_schedule(self, card_id: uuid.UUID, schedule: Schedule) -> None: ...
