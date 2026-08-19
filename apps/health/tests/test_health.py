from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from apps.health import router
from apps.shared.observability.loop import LoopHealth


def test_liveness_returns_200(driver):
    response = driver.client().get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_when_db_ok(driver):
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.health.router._admin_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = mock_conn
        response = driver.client().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_db_down(driver):
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = OperationalError("connect", {}, Exception("refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.health.router._admin_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = mock_conn
        response = driver.client().get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_a_readiness_probe_that_starts_failing_says_why(driver, monkeypatch):
    """A degraded readiness used to be a bare 503: the exception was caught and dropped, and
    ``/health/ready`` is in the request logger's skip list, so a database the app could not reach
    left no trace at all — the one outage an operator most needs named.

    Probed on a timer (the container healthcheck polls every ten seconds), so it is a loop like
    any other: the transition is the bug, what follows is the same outage still running.
    """
    monkeypatch.setattr(router, "_health", LoopHealth(router.log, "health.ready"))
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = OperationalError("connect", {}, Exception("refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.health.router._admin_engine") as mock_engine, capture_logs() as logs:
        mock_engine.return_value.connect.return_value = mock_conn
        driver.client().get("/health/ready")
        driver.client().get("/health/ready")

    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("health.ready_failed", "error"),
        ("health.ready_failed", "warning"),
    ]
