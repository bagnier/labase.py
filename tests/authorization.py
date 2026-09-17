"""Authorization rules, stated once and checked at both doors.

A rule says whether a role may act on a target row. The database holds it (the policy), and the
route repeats it so the refusal is a clean 403. Each app writes its rules once, in a ``RuleBook``,
and ``tests/test_authorization_rules.py`` reads every book twice: once sending each action as SQL
on the API role, the way a PostgREST client would, and once through the route, whose sessions
bypass RLS, so only the route's own check answers. An act no route offers has the database door
alone.

``tests/test_db_privileges.py`` checks the books' reach: every table whose policies call an
authorization helper has rules.
"""

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, NewType

import httpx
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.infra.repository import OrganizationRepository
from apps.organizations.tests.given_helpers import add_membership
from tests.e2e.drivers.api import ApiDriver
from tests.e2e.sql_setup import run_sql
from tests.rls import acting_as

# Who acts on a rule, and who only stands in an org to be acted on.
Role = Literal["owner", "member"]
Stranger = Literal["other", "outsider"]
Person = Role | Stranger
_PEOPLE: tuple[Person, ...] = ("owner", "member", "other", "outsider")
_STRANGERS: tuple[Stranger, ...] = ("other", "outsider")

# A GoTrue user id, kept as text: it fills SQL parameters and route placeholders as is.
UserId = NewType("UserId", str)

# What a target is known by: its values fill the SQL parameters and the route's placeholders.
Fields = dict[str, str]


@dataclass(frozen=True)
class Route:
    """``path`` is relative to ``/{org_handle}``; it and ``body`` may name a target's fields."""

    method: str
    path: str
    body: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """``sql`` returns a row when it went through, and may name ``:org_id``, ``:me`` (the actor)
    and the target's fields. ``route`` is None when no route offers the act."""

    name: str
    sql: str
    route: Route | None


@dataclass(frozen=True)
class Rule:
    table: str
    role: Role
    action: Action
    target: str
    allowed: bool

    def __str__(self) -> str:
        verdict = "may" if self.allowed else "may-not"
        return f"{self.role}-{verdict}-{self.action.name}-{self.target}"


@dataclass(frozen=True)
class Org:
    """An org with its owner, a member, a second member (``other``) and a user outside it
    (``outsider``), by user id."""

    id: str
    handle: str
    people: dict[Person, UserId]


@dataclass(frozen=True)
class RuleBook:
    """An app's rules, and how each door gets the targets they name — seeded as the owner."""

    rules: list[Rule]
    seed_in_db: Callable[[AsyncSession, Org], Awaitable[dict[str, Fields]]]
    seed_through_routes: Callable[[httpx.Client, Org], dict[str, Fields]]


def no_route_targets(owner: httpx.Client, org: Org) -> dict[str, Fields]:
    """For a book whose acts no route offers."""
    return {}


async def went_through(session: AsyncSession, action: Action, params: dict[str, Any]) -> bool:
    """Whether RLS let ``action`` act: a policy refuses by filtering the row out (``USING``) or by
    raising (``WITH CHECK``), and both mean no."""
    try:
        async with session.begin_nested():
            return await session.scalar(text(action.sql), params) is not None
    except ProgrammingError as error:
        if "row-level security" not in str(error):
            raise
        return False


def sent_through(client: httpx.Client, org: Org, route: Route, fields: Fields) -> httpx.Response:
    body = {key: value.format(**fields) for key, value in route.body.items()}
    return client.request(
        route.method, f"/{org.handle}{route.path.format(**fields)}", json=body or None
    )


@asynccontextmanager
async def an_org_in_db(session: AsyncSession) -> AsyncGenerator[Org]:
    people: dict[Person, UserId] = {
        person: UserId(create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")) for person in _PEOPLE
    }
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, people["owner"]):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(people["owner"])
                )
                for role in ("member", "other"):
                    await session.execute(
                        text("insert into memberships (org_id, user_id) values (:org, :user)"),
                        {"org": org.id, "user": people[role]},
                    )
            yield Org(str(org.id), org.handle, people)
        finally:
            await outer.rollback()
    finally:
        for user in people.values():
            delete_user(user)


_OWNER = "owner-acme@example.com"  # the owner `sign_in_as_member_of_org` seats
_MEMBER = "member@example.com"


@contextmanager
def strangers() -> Iterator[dict[Stranger, UserId]]:
    """``other`` and ``outsider``, who never act at the route door, so they need an account and
    no session. Deleted only once the test transactions that locked their rows are gone."""
    people: dict[Stranger, UserId] = {
        stranger: UserId(create_user(f"{uuid.uuid4()}@rules.local", "Test1234!"))
        for stranger in _STRANGERS
    }
    try:
        yield people
    finally:
        for user in people.values():
            delete_user(user)


def an_org_through_routes(
    driver: ApiDriver, strangers: dict[Stranger, UserId]
) -> tuple[Org, dict[Role, httpx.Client]]:
    """The org, committed, and a signed-in client per role."""
    driver.sign_in_as_member_of_org(_MEMBER, "Acme")
    # Signed in, not registered: registering an existing account answers slowly on purpose.
    driver.clear_acting_email()
    driver.sign_in(_OWNER, driver.PASSWORD)
    owner = driver.client()
    driver.set_acting_email(_MEMBER)
    seats = run_sql(
        "select m.org_id::text as org_id, m.user_id::text as user_id, m.role::text as role"
        " from memberships m join organizations o on o.id = m.org_id where o.handle = :handle",
        {"handle": driver.active_org_handle},
        fetch=True,
    )
    org_id = seats[0]["org_id"]
    add_membership(org_id, strangers["other"])
    seated = {seat["role"]: UserId(seat["user_id"]) for seat in seats}
    people: dict[Person, UserId] = {
        "owner": seated["owner"],
        "member": seated["member"],
        **strangers,
    }
    org = Org(org_id, driver.active_org_handle, people)
    return org, {"owner": owner, "member": driver.client()}
