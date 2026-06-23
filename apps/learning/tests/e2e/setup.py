"""Direct-DB fixtures for BDD setup (catalog + preset progress).

These build the deck/card catalog and pre-existing learning state that scenarios
assume. The driver supplies the right session: a test-transaction session for the
API driver (rolled back) or a committed admin session for the browser driver.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.learning.domain.models import (
    Card,
    CardState,
    Deck,
    DeckSubscription,
)
from apps.learning.domain.service import interval_for_level


async def create_deck(
    session: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    resource: str | None,
    position: int,
    cards: list[dict],
) -> Deck:
    deck = await session.scalar(select(Deck).where(Deck.org_id == org_id, Deck.name == name))
    if deck is None:
        deck = Deck(org_id=org_id, name=name, resource=resource, position=position)
        session.add(deck)
        await session.flush()
    for i, c in enumerate(cards):
        exists = await session.scalar(
            select(Card).where(Card.deck_id == deck.id, Card.external_id == c["external_id"])
        )
        if exists is None:
            session.add(
                Card(
                    org_id=org_id,
                    deck_id=deck.id,
                    external_id=c["external_id"],
                    question=c["question"],
                    answer=c["answer"],
                    resource=c.get("resource") or None,
                    position=i,
                )
            )
    await session.flush()
    return deck


async def subscribe(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, deck_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(DeckSubscription).where(
            DeckSubscription.user_id == user_id, DeckSubscription.deck_id == deck_id
        )
    )
    if exists is None:
        session.add(DeckSubscription(org_id=org_id, user_id=user_id, deck_id=deck_id))
        await session.flush()


async def set_state(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    card_id: uuid.UUID,
    level: int,
    last_reviewed_on: date,
) -> None:
    next_on = last_reviewed_on + timedelta(days=interval_for_level(level))
    state = await session.scalar(
        select(CardState).where(CardState.user_id == user_id, CardState.card_id == card_id)
    )
    if state is None:
        state = CardState(org_id=org_id, user_id=user_id, card_id=card_id)
        session.add(state)
    state.level = level
    state.last_reviewed_on = last_reviewed_on
    state.next_review_on = next_on
    await session.flush()


async def get_state(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, external_id: str
) -> dict:
    """Reads a card's review state (level + dates) through SQLAlchemy.

    The browser driver validates spaced-repetition state from here rather than the JSON
    API: these dates are not surfaced in the rendered HTML, so the DB is the only non-REST
    source of truth.
    """
    card_id = await card_id_by_external(session, org_id, external_id)
    state = await session.scalar(
        select(CardState).where(CardState.user_id == user_id, CardState.card_id == card_id)
    )
    return {
        "level": state.level if state else 0,
        "last_reviewed_on": state.last_reviewed_on.isoformat()
        if state and state.last_reviewed_on
        else None,
        "next_review_on": state.next_review_on.isoformat()
        if state and state.next_review_on
        else None,
    }


async def deck_card_ids(session: AsyncSession, deck_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(select(Card.id).where(Card.deck_id == deck_id))
    return list(rows)


async def card_id_by_external(
    session: AsyncSession, org_id: uuid.UUID, external_id: str
) -> uuid.UUID:
    cid = await session.scalar(
        select(Card.id).where(Card.org_id == org_id, Card.external_id == external_id)
    )
    assert cid is not None, f"Card {external_id!r} not found"
    return cid


async def deck_id_by_name(session: AsyncSession, org_id: uuid.UUID, name: str) -> uuid.UUID:
    did = await session.scalar(select(Deck.id).where(Deck.org_id == org_id, Deck.name == name))
    assert did is not None, f"Deck {name!r} not found"
    return did
