"""Resolving user ids to emails for console labels: a gone or unparseable account never fails
the page."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError
from supabase_auth.errors import AuthApiError

from apps.auth.infra.user_repository import resolve_user_emails
from apps.shared.logs import capture


class _RequiresIdentityData(BaseModel):
    identity_data: dict


def _unparseable_record() -> ValidationError:
    """The real ``ValidationError`` of an identity without ``identity_data``."""
    with pytest.raises(ValidationError) as caught:
        _RequiresIdentityData.model_validate({})
    return caught.value


def _directory(records: dict[uuid.UUID, str | Exception]) -> MagicMock:
    """Each id maps to its email, or to the exception reading it raises."""

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
    """One unreadable record must not fail the concurrent batch, hence the page."""
    healthy, malformed = uuid.uuid7(), uuid.uuid7()
    client = _directory({healthy: "ada@example.com", malformed: _unparseable_record()})

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        emails = await resolve_user_emails([healthy, malformed])

    assert emails == {healthy: "ada@example.com", malformed: ""}


@pytest.mark.asyncio
async def test_an_id_the_directory_no_longer_knows_blanks_too():
    healthy, gone = uuid.uuid7(), uuid.uuid7()
    client = _directory(
        {healthy: "ada@example.com", gone: AuthApiError("user not found", 404, "user_not_found")}
    )

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        emails = await resolve_user_emails([healthy, gone])

    assert emails == {healthy: "ada@example.com", gone: ""}


# A broken directory fails every id at once: it must open one issue, not one per id.


@pytest.fixture(autouse=True)
def _empty_capture_queue():
    capture._QUEUE.clear()
    yield
    capture._QUEUE.clear()


@pytest.mark.asyncio
async def test_a_directory_that_is_down_is_one_issue_for_the_whole_batch():
    ids = [uuid.uuid7() for _ in range(3)]
    client = _directory({uid: ConnectionError("gotrue is unreachable") for uid in ids})

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        emails = await resolve_user_emails(ids)

    assert (emails, [type(c.exc) for c in capture._QUEUE]) == (
        dict.fromkeys(ids, ""),
        [ConnectionError],
    )


@pytest.mark.asyncio
async def test_ids_the_directory_no_longer_knows_are_not_a_bug():
    ids = [uuid.uuid7() for _ in range(2)]
    client = _directory({uid: AuthApiError("user not found", 404, "user_not_found") for uid in ids})

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await resolve_user_emails(ids)

    assert list(capture._QUEUE) == []


@pytest.mark.asyncio
async def test_a_batch_is_as_broken_as_its_worst_answer():
    """A gone account alongside a real outage must not let the refusal speak for the batch."""
    gone, broken = uuid.uuid7(), uuid.uuid7()
    client = _directory(
        {
            gone: AuthApiError("user not found", 404, "user_not_found"),
            broken: ConnectionError("gotrue is unreachable"),
        }
    )

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await resolve_user_emails([gone, broken])

    assert [type(c.exc) for c in capture._QUEUE] == [ConnectionError]
