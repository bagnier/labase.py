import uuid
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.domain.models import (
    Card,
    CardState,
    Deck,
    DeckSubscription,
    Schedule,
)


@dataclass(frozen=True)
class CatalogRow:
    deck: Deck
    card: Card
    state: CardState | None


class LearningRepository:
    """Org-scoped catalog with per-user progress (subscriptions/states/reviews)."""

    def __init__(self, session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id
        self.user_id = user_id

    async def get_deck_by_name(self, name: str) -> Deck | None:
        return await self.session.scalar(
            select(Deck).where(Deck.org_id == self.org_id, Deck.name == name)
        )

    async def get_card_by_external(self, external_id: str) -> Card | None:
        return await self.session.scalar(
            select(Card).where(Card.org_id == self.org_id, Card.external_id == external_id)
        )

    async def subscribe(self, deck_id: uuid.UUID) -> None:
        exists = await self.session.scalar(
            select(DeckSubscription).where(
                DeckSubscription.user_id == self.user_id, DeckSubscription.deck_id == deck_id
            )
        )
        if exists is None:
            self.session.add(
                DeckSubscription(org_id=self.org_id, user_id=self.user_id, deck_id=deck_id)
            )
            await self.session.flush()

    async def catalog(self) -> list[CatalogRow]:
        """All cards of the user's subscribed decks with this user's state, in deck/card order."""
        rows = await self.session.execute(
            select(Deck, Card, CardState)
            .join(DeckSubscription, DeckSubscription.deck_id == Deck.id)
            .join(Card, Card.deck_id == Deck.id)
            .outerjoin(
                CardState,
                and_(CardState.card_id == Card.id, CardState.user_id == self.user_id),
            )
            .where(DeckSubscription.user_id == self.user_id, Deck.org_id == self.org_id)
            .order_by(Deck.position, Card.position)
        )
        return [CatalogRow(deck=d, card=c, state=s) for d, c, s in rows.all()]

    async def get_state(self, card_id: uuid.UUID) -> CardState | None:
        return await self.session.scalar(
            select(CardState).where(CardState.card_id == card_id, CardState.user_id == self.user_id)
        )

    async def apply_schedule(self, card_id: uuid.UUID, schedule: Schedule) -> None:
        state = await self.get_state(card_id)
        if state is None:
            state = CardState(org_id=self.org_id, user_id=self.user_id, card_id=card_id)
            self.session.add(state)
        state.level = schedule.level
        state.last_reviewed_on = schedule.last_reviewed_on
        state.next_review_on = schedule.next_review_on
        await self.session.flush()
