"""Welcome deck the learning context drops into a freshly created organisation.

Public surface consumed by the composition root (:mod:`app.seeding`) via the
``org.created`` hook. Runs inside the org-creating transaction.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.domain.models import Card, Deck

_WELCOME_DECK = "Welcome"
_WELCOME_CARDS = [
    {
        "external_id": "what-is-a-deck",
        "question": "What is a deck?",
        "answer": "A collection of flashcards you review with spaced repetition.",
    },
    {
        "external_id": "how-to-review",
        "question": "How does reviewing work?",
        "answer": "Cards you know come back less often; cards you miss come back sooner.",
    },
]


async def seed(session: AsyncSession, org_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    deck = Deck(org_id=org_id, name=_WELCOME_DECK, position=0)
    session.add(deck)
    await session.flush()
    for position, card in enumerate(_WELCOME_CARDS):
        session.add(
            Card(
                org_id=org_id,
                deck_id=deck.id,
                external_id=card["external_id"],
                question=card["question"],
                answer=card["answer"],
                position=position,
            )
        )
    await session.flush()
