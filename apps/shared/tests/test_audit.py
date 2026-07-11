"""Audit trail write path — the failure seam must degrade, never raise."""

from unittest.mock import patch

import pytest

from apps.shared.observability.audit import _insert_audit_log


@pytest.mark.asyncio
async def test_failed_audit_write_logs_a_warning_instead_of_raising():
    # Regression: the warning passed `event=` as a kwarg, colliding with
    # structlog's positional message parameter — the fallback itself raised,
    # turning a lost audit row into a crashed background task.
    with (
        patch(
            "apps.shared.observability.audit.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ),
        patch("apps.shared.observability.audit.log") as log,
    ):
        await _insert_audit_log("info", "auth.signed_in", "not-a-uuid", None, None, None, {})
    log.warning.assert_called_once_with(
        "audit.write_failed", audit_event="auth.signed_in", user_id="not-a-uuid"
    )
