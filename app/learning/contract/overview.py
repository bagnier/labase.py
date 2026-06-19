"""The learning context's dashboard overview.

Public surface consumed by the composition root (:mod:`app.overviews`). Org-scoped:
counts the org's decks and cards. Personal subscriptions and review states are
user-scoped and deliberately excluded — the dashboard is org-scoped.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.domain.models import Card, Deck
from app.organizations.contract.overviews import Overview


async def overview(session: AsyncSession, org_id: uuid.UUID) -> Overview:
    decks = await session.scalar(
        select(func.count()).select_from(Deck).where(Deck.org_id == org_id)
    )
    cards = await session.scalar(
        select(func.count()).select_from(Card).where(Card.org_id == org_id)
    )
    decks, cards = decks or 0, cards or 0
    if decks:
        lines = [f"{decks} deck" + ("s" if decks > 1 else ""), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return Overview(
        key="learning",
        title="Learning",
        icon="graduation-cap",
        href="learning",
        template="learning/_overview.html",
        data={"lines": lines, "recent": []},
    )
