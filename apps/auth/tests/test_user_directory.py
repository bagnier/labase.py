"""Reading the auth directory — resolving user ids to emails for the console's screens.

The console labels ids it finds in logs and events with the account's email. Those ids come from
history, and history outlives the directory: an account can be gone, or its GoTrue record can be
something the SDK's own models refuse to parse. Neither is a reason to fail the page that merely
wanted a label, which is what these tests pin.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError
from supabase_auth.errors import AuthApiError

from apps.auth.infra.user_repository import resolve_user_emails


class _RequiresIdentityData(BaseModel):
    identity_data: dict


def _unparseable_record() -> ValidationError:
    """The failure GoTrue produced for real: a user whose identity carries no ``identity_data``,
    a field the SDK's pydantic model declares required. Built here the same way — by validating a
    record that misses a required field — so the test breaks on the real exception type, not a
    stand-in."""
    with pytest.raises(ValidationError) as caught:
        _RequiresIdentityData.model_validate({})
    return caught.value


def _directory(records: dict[uuid.UUID, str | Exception]) -> MagicMock:
    """A stubbed GoTrue admin API: each id maps to the email it resolves to, or to the exception
    reading it raises."""

    def get_user_by_id(user_id: str) -> SimpleNamespace:
        record = records[uuid.UUID(user_id)]
        if isinstance(record, Exception):
            raise record
        return SimpleNamespace(user=SimpleNamespace(email=record))

    client = MagicMock()
    client.auth.admin.get_user_by_id = get_user_by_id
    return client


@pytest.mark.asyncio
async def test_a_record_the_sdk_cannot_parse_blanks_only_that_id():
    """Regression: this took down the whole Logs screen with a 500.

    The batch resolves every id concurrently, so an exception escaping one of them propagates out
    of the gather and fails the request — one unreadable account out of hundreds was enough. Only
    ``AuthApiError`` was caught, and a malformed record raises a ``ValidationError`` instead."""
    healthy, malformed = uuid.uuid7(), uuid.uuid7()
    client = _directory({healthy: "ada@example.com", malformed: _unparseable_record()})

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        emails = await resolve_user_emails([healthy, malformed])

    assert emails == {healthy: "ada@example.com", malformed: ""}


@pytest.mark.asyncio
async def test_an_id_the_directory_no_longer_knows_blanks_too():
    """The case the code already handled: a deleted account, or a stale id read off an old log
    line. It resolves to a blank label, never an error."""
    healthy, gone = uuid.uuid7(), uuid.uuid7()
    client = _directory(
        {healthy: "ada@example.com", gone: AuthApiError("user not found", 404, "user_not_found")}
    )

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        emails = await resolve_user_emails([healthy, gone])

    assert emails == {healthy: "ada@example.com", gone: ""}
