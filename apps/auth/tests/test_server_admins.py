"""Setting ``app_metadata.role``: an unreadable echo of a write that landed is not a failure
(see ``user_repository``)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from apps.auth.infra.user_repository import set_server_admin
from apps.auth.tests.test_user_directory import _unparseable_record


@pytest.mark.asyncio
async def test_set_server_admin_survives_a_record_the_sdk_cannot_parse():
    """A user with an anonymized identity: the role is written, nothing raises."""
    user_id = uuid.uuid7()
    calls: list[tuple[str, dict]] = []

    def update_user_by_id(uid: str, attributes: dict) -> None:
        # A fake: a healthy GoTrue cannot produce this failure.
        calls.append((uid, attributes))
        raise _unparseable_record()

    client = MagicMock()
    client.auth.admin.update_user_by_id = update_user_by_id

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await set_server_admin(user_id, is_admin=True)

    assert calls == [(str(user_id), {"app_metadata": {"role": "admin"}})]
