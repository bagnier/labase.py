"""Writing the admin claim — setting ``app_metadata.role`` through the GoTrue admin API.

The SDK parses the response *after* the server applied the update: a non-2xx raises
``AuthApiError`` before any parsing, so a ``ValidationError`` can only mean the write landed and
the returned record is unreadable (an anonymized identity missing ``identity_data``). That must
not fail the caller — the action succeeded, only the echo is malformed.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from apps.auth.infra.user_repository import set_server_admin
from apps.auth.tests.test_user_directory import _unparseable_record


@pytest.mark.asyncio
async def test_set_server_admin_survives_a_record_the_sdk_cannot_parse():
    """Regression: promoting a user whose identity GoTrue anonymized raised out of the handler
    and sent the queue task into retry, although the role was already written."""
    user_id = uuid.uuid7()
    calls: list[tuple[str, dict]] = []

    def update_user_by_id(uid: str, attributes: dict) -> None:
        # Fake of a service we own (the GoTrue admin wrapper): the failure path cannot be staged
        # on a healthy client — the SDK only raises this after the server took the write.
        calls.append((uid, attributes))
        raise _unparseable_record()

    client = MagicMock()
    client.auth.admin.update_user_by_id = update_user_by_id

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await set_server_admin(user_id, is_admin=True)

    assert calls == [(str(user_id), {"app_metadata": {"role": "admin"}})]
