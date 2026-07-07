"""How the learning context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds a welcome deck on ``OrgCreated``.
"""

from sqlalchemy import func, select

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.learning.contract import settings
from apps.learning.domain.models import Card, Deck
from apps.learning.infra.router import router
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.shared.host import Host, NavItem
from apps.shared.persistence.database import admin_session_factory
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.shared.text import overview_from_count

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


# Mounts an org-scoped router under /{org_handle}; mounted last (see apps.main).


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.register_settings(settings, _declare_settings())
    if not settings.enabled:
        return
    host.app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Learning", "book-open", "learning/sessions", "/learning", order=20))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


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
    decks = await query.session.scalar(select(func.count()).select_from(Deck)) or 0
    cards = await query.session.scalar(select(func.count()).select_from(Card)) or 0
    if decks:
        lines = [*overview_from_count(decks, "deck", "No decks yet"), f"{cards} cards"]
    else:
        lines = ["No decks yet"]
    return ConsoleOverview(
        key="learning", title="Learning", icon="book-open", data={"lines": lines}
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
