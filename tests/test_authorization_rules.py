"""Every authorization rule, at both doors (see ``tests/authorization.py``)."""

from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.authorization import (
    Route,
    Rule,
    RuleBook,
    Stranger,
    UserId,
    an_org_in_db,
    an_org_through_routes,
    sent_through,
    strangers,
    went_through,
)
from tests.e2e.drivers.api import ApiDriver
from tests.rls import acting_as, as_api_client
from tests.rulebooks import BOOKS

_AT_THE_DATABASE = [
    pytest.param(book, rule, id=f"{rule.table}:{rule}") for book in BOOKS for rule in book.rules
]
_AT_THE_ROUTE = [
    pytest.param(book, rule, rule.action.route, id=f"{rule.table}:{rule}")
    for book in BOOKS
    for rule in book.rules
    if rule.action.route is not None
]


@pytest.fixture(scope="module")
def route_strangers() -> Iterator[dict[Stranger, UserId]]:
    with strangers() as people:
        yield people


@pytest.mark.asyncio
@pytest.mark.parametrize(("book", "rule"), _AT_THE_DATABASE)
async def test_the_database_gives_each_rule_its_verdict(
    db_session: AsyncSession, book: RuleBook, rule: Rule
):
    async with an_org_in_db(db_session) as org:
        async with acting_as(db_session, org.people["owner"]):
            targets = await book.seed_in_db(db_session, org)
        me = org.people[rule.role]
        async with as_api_client(db_session, me):
            acted = await went_through(
                db_session, rule.action, {"org_id": org.id, "me": me, **targets[rule.target]}
            )

    assert acted == rule.allowed


@pytest.mark.parametrize(("book", "rule", "route"), _AT_THE_ROUTE)
def test_the_route_gives_each_rule_its_verdict(
    driver: ApiDriver,
    route_strangers: dict[Stranger, UserId],
    book: RuleBook,
    rule: Rule,
    route: Route,
):
    org, clients = an_org_through_routes(driver, route_strangers)
    targets = book.seed_through_routes(clients["owner"], org)

    response = sent_through(clients[rule.role], org, route, targets.get(rule.target, {}))

    assert response.is_success == rule.allowed, response.text
