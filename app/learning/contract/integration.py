"""How the learning context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`app.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds a welcome deck on ``OrgCreated``.
"""

from fastapi import FastAPI
from sqlalchemy import func, select

from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import (
    ConsoleSettingsQuery,
    SettingDef,
    SettingsGroup,
    SupabaseLink,
)
from app.learning.domain.models import Card, Deck
from app.learning.infra.router import router
from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.overviews import Overview, OverviewQuery
from app.shared.host import Host
from app.shared.persistence.database import admin_session_factory

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


# Mounts an org-scoped router under /{org_handle}; registered last (see app.main).
MOUNTS_UNDER_ORG_HANDLE = True


def mount(app: FastAPI, host: Host) -> None:
    app.include_router(router, prefix=ORG_PREFIX)
    host.events.on(OverviewQuery, _overview)
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.events.on(ConsoleSettingsQuery, _console_settings)
    host.events.on(OrgCreated, _seed)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    decks = await query.session.scalar(select(func.count()).select_from(Deck)) or 0
    cards = await query.session.scalar(select(func.count()).select_from(Card)) or 0
    if decks:
        lines = [f"{decks} deck" + ("s" if decks > 1 else ""), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return ConsoleOverview(
        key="learning", title="Learning", icon="book-open", data={"lines": lines}
    )


async def _console_settings(query: ConsoleSettingsQuery) -> SettingsGroup:
    return SettingsGroup(
        app="learning",
        defs=[
            SettingDef("sharing_enabled", "boolean", "true", "Allow members to share decks"),
            SettingDef("daily_review_limit", "number", "100", "Max cards reviewed per day"),
        ],
        supabase=SupabaseLink("Browse decks and cards in Supabase", table="decks"),
    )


async def _overview(query: OverviewQuery) -> Overview:
    decks = await query.session.scalar(
        select(func.count()).select_from(Deck).where(Deck.org_id == query.org_id)
    )
    cards = await query.session.scalar(
        select(func.count()).select_from(Card).where(Card.org_id == query.org_id)
    )
    decks, cards = decks or 0, cards or 0
    if decks:
        lines = [f"{decks} deck" + ("s" if decks > 1 else ""), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return Overview(
        key="learning",
        title="Learning",
        icon="book-open",
        href="learning",
        template="learning/_overview.html",
        data={"lines": lines, "recent": []},
    )


async def _seed(event: OrgCreated) -> None:
    async with admin_session_factory()() as session:
        deck = Deck(org_id=event.org_id, name=_WELCOME_DECK, position=0)
        session.add(deck)
        await session.flush()
        for position, card in enumerate(_WELCOME_CARDS):
            session.add(
                Card(
                    org_id=event.org_id,
                    deck_id=deck.id,
                    external_id=card["external_id"],
                    question=card["question"],
                    answer=card["answer"],
                    position=position,
                )
            )
        await session.commit()
