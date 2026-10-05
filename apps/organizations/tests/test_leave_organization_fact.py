"""A racing second leave deletes nothing and records no second `MemberLeft`.

The API driver serializes requests, so a second call would be refused by ``CurrentMembership``
first: the handler is called directly, on a real session and database.
"""

import uuid

from fastapi import Request
from sqlalchemy import text

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.tests.given_helpers import user_id_for_email
from apps.organizations.infra.repository import OrganizationRepository
from apps.organizations.infra.router import leave_organization


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": "/acme/members/me",
        "headers": [],
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _member_left_count(driver, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    async def read() -> int:
        async with driver.test_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT count(*) FROM business_events "
                    "WHERE kind = 'organizations.member_left' "
                    "AND org_id = :org_id AND user_id = :user_id"
                ),
                {"org_id": str(org_id), "user_id": str(user_id)},
            )
            return result.scalar_one()

    return driver.run(read())


def test_leaving_records_the_fact_once(driver):
    email = "leave-once@example.com"
    driver.sign_in_as_member_of_org(email, "Leave Once")
    org = driver.client_for(email).get("/organizations").json()[0]
    org_id = uuid.UUID(org["id"])
    user_id = uuid.UUID(user_id_for_email(email))

    driver.leave_org()

    assert driver.response.status_code == 204
    assert _member_left_count(driver, org_id, user_id) == 1


def test_leaving_an_already_gone_membership_records_no_second_fact(driver):
    email = "leave-race@example.com"
    driver.sign_in_as_member_of_org(email, "Leave Race")
    org = driver.client_for(email).get("/organizations").json()[0]
    org_id = uuid.UUID(org["id"])
    user_id = uuid.UUID(user_id_for_email(email))

    async def leave_twice() -> None:
        async with driver.test_session_factory()() as session:
            repo = OrganizationRepository(session)
            membership = await repo.get_membership(org_id, user_id)
            assert membership is not None
            current_user = AuthenticatedUser(id=user_id, email=email)
            await leave_organization(_request(), current_user, repo, org_id, membership)
            await session.commit()
            await leave_organization(_request(), current_user, repo, org_id, membership)
            await session.commit()

    driver.run(leave_twice())

    assert _member_left_count(driver, org_id, user_id) == 1
