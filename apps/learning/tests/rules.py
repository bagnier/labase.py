"""Who may change the decks and their cards.

Members read and study; owners write the catalogue. No route writes it, so these rules have the
database door alone.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.authorization import Action, Fields, Org, Rule, RuleBook, no_route_targets

CREATE_DECK = Action(
    name="create",
    sql="insert into decks (org_id, name) values (:org_id, 'New deck') returning id",
    route=None,
)
EDIT_DECK = Action(
    name="edit",
    sql="update decks set name = 'Changed' where id = :deck_id returning id",
    route=None,
)
DELETE_DECK = Action(
    name="delete",
    sql="delete from decks where id = :deck_id returning id",
    route=None,
)
CREATE_CARD = Action(
    name="create",
    sql="insert into cards (org_id, deck_id, external_id, question, answer)"
    " values (:org_id, :deck_id, 'new', 'Q', 'A') returning id",
    route=None,
)
EDIT_CARD = Action(
    name="edit",
    sql="update cards set question = 'Changed' where id = :card_id returning id",
    route=None,
)
DELETE_CARD = Action(
    name="delete",
    sql="delete from cards where id = :card_id returning id",
    route=None,
)


async def _seed_in_db(session: AsyncSession, org: Org) -> dict[str, Fields]:
    deck_id = await session.scalar(
        text("insert into decks (org_id, name) values (:org_id, 'Deck') returning id::text"),
        {"org_id": org.id},
    )
    card_id = await session.scalar(
        text(
            "insert into cards (org_id, deck_id, external_id, question, answer)"
            " values (:org_id, :deck_id, 'card', 'Q', 'A') returning id::text"
        ),
        {"org_id": org.id, "deck_id": deck_id},
    )
    return {"deck": {"deck_id": deck_id}, "card": {"deck_id": deck_id, "card_id": card_id}}


LEARNING = RuleBook(
    rules=[
        Rule("decks", "member", CREATE_DECK, "deck", allowed=False),
        Rule("decks", "owner", CREATE_DECK, "deck", allowed=True),
        Rule("decks", "member", EDIT_DECK, "deck", allowed=False),
        Rule("decks", "owner", EDIT_DECK, "deck", allowed=True),
        Rule("decks", "member", DELETE_DECK, "deck", allowed=False),
        Rule("decks", "owner", DELETE_DECK, "deck", allowed=True),
        Rule("cards", "member", CREATE_CARD, "card", allowed=False),
        Rule("cards", "owner", CREATE_CARD, "card", allowed=True),
        Rule("cards", "member", EDIT_CARD, "card", allowed=False),
        Rule("cards", "owner", EDIT_CARD, "card", allowed=True),
        Rule("cards", "member", DELETE_CARD, "card", allowed=False),
        Rule("cards", "owner", DELETE_CARD, "card", allowed=True),
    ],
    seed_in_db=_seed_in_db,
    seed_through_routes=no_route_targets,
)
