"""How the learning context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds a welcome deck on ``OrganizationCreated``.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.learning.contract.events import CardReviewed
from apps.learning.domain.models import Card, Deck
from apps.learning.infra.router import router
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_org_welcome
from apps.shared.host import AppManifest, Host, MountPhase, NavItem
from apps.shared.persistence.repository import count_where
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.shared.text import overview_from_count

PHASE = MountPhase.ORG

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


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            provides=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            nav=[NavItem("Learning", "book-open", "learning/sessions", "/learning", order=20)],
            emits=[CardReviewed],
            consumes_when_enabled=[(OrganizationCreated, "learning_welcome", _seed)],
            provides_when_enabled=[(OverviewQuery, _overview)],
        )
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="learning",
        defs=[
            feature_switch(),
            SettingDef("sharing_enabled", "boolean", "true", "Allow members to share decks"),
            SettingDef("daily_review_limit", "number", "100", "Max cards reviewed per day"),
        ],
        supabase=SupabaseLink("Browse decks and cards in Supabase", table="decks"),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    decks = await count_where(query.session, Deck)
    cards = await count_where(query.session, Card)
    if decks:
        lines = [*overview_from_count(decks, "deck", "No decks yet"), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return ConsoleOverview(
        key="learning", title="Learning", icon="book-open", data={"lines": lines}
    )


async def _overview(query: OverviewQuery) -> Overview:
    decks = await count_where(query.session, Deck, Deck.org_id == query.org_id)
    cards = await count_where(query.session, Card, Card.org_id == query.org_id)
    if decks:
        lines = [*overview_from_count(decks, "deck", "No decks yet"), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return Overview(
        key="learning",
        title="Learning",
        icon="book-open",
        href="learning/sessions",
        template="learning/_overview.html",
        data={"lines": lines, "recent": []},
    )


async def _seed(session: AsyncSession, event: OrganizationCreated) -> None:
    await seed_org_welcome(session, event.org_id, _seed_welcome)


async def _seed_welcome(session: AsyncSession, org_id: uuid.UUID, _owner_id: uuid.UUID) -> None:
    # Decks and cards are org-scoped, not owner-scoped, so the owner isn't needed here.
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
