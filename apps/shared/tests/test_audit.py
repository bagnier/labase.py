"""Business-events write path — the failure seam must degrade, never raise."""

from unittest.mock import patch

import pytest

from apps.shared.observability.business_events import insert_business_event


@pytest.mark.asyncio
async def test_failed_write_logs_a_warning_instead_of_raising():
    # Regression: the warning must not pass `event=`/`kind=` under structlog's positional
    # message key, and a lost row must never crash the fire-and-forget write task.
    with (
        patch(
            "apps.shared.observability.business_events.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ),
        patch("apps.shared.observability.business_events.log") as log,
    ):
        await insert_business_event(
            kind="auth.signed_in",
            level="info",
            user_id="not-a-uuid",
            ip=None,
            org_id=None,
            request_id=None,
            payload=None,
        )
    log.warning.assert_called_once_with(
        "business_event.write_failed", kind="auth.signed_in", user_id="not-a-uuid"
    )
