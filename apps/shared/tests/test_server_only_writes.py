"""The queue, its ledger and the journal are written by the server, never by an API client.

PostgREST runs a signed-in request on the ``authenticated`` role, so anything granted to that role
is open to any account. These writes belong to the server's own role, which only the app's
connection can take on.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.rls import acting_as, as_api_client

_UID = str(uuid.uuid4())

_ENQUEUE = text("insert into task_queue (topic, payload) values ('email.send', '{}')")
_MARK_CONSUMED = text(
    "insert into consumed_events (consumer, event_id) values ('any', gen_random_uuid())"
)
_RECORD_FACT = text(
    "select record_business_event("
    "'todo', 'created', 'x', null, null, null, null, null, null, null, null, null, '{}')"
)


@pytest.mark.parametrize("statement", [_ENQUEUE, _MARK_CONSUMED, _RECORD_FACT])
@pytest.mark.asyncio
async def test_an_api_client_cannot_write_what_only_the_server_writes(
    db_session: AsyncSession, statement
):
    async with as_api_client(db_session, _UID):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with db_session.begin_nested():
                await db_session.execute(statement)


@pytest.mark.parametrize("statement", [_ENQUEUE, _MARK_CONSUMED, _RECORD_FACT])
@pytest.mark.asyncio
async def test_the_app_session_writes_what_only_the_server_writes(
    db_session: AsyncSession, statement
):
    async with acting_as(db_session, _UID), db_session.begin_nested() as savepoint:
        await db_session.execute(statement)
        await savepoint.rollback()
