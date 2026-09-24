from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from apps.health import router
from apps.shared.logs.loop import LoopHealth


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


def test_a_readiness_probe_answering_503_leaves_a_finished_line(driver):
    """``/health/ready`` is silent while healthy — a probe every ten seconds would otherwise be
    most of the timeline — but a 503 is our fault whatever asked, so it earns the same
    ``request.finished`` line any other 5xx does."""
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = OperationalError("connect", {}, Exception("refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.health.router._admin_engine") as mock_engine, capture_logs() as logs:
        mock_engine.return_value.connect.return_value = mock_conn
        driver.client().get("/health/ready")

    finished = [
        (e["event"], e["log_level"], e["status"]) for e in logs if e["event"] == "request.finished"
    ]
    assert finished == [("request.finished", "error", 503)]


def test_a_readiness_probe_that_starts_failing_says_why(driver, monkeypatch):
    """A degraded readiness used to be a bare 503 with the exception caught and dropped, naming
    neither the outage nor its reason. ``request.finished`` (see ``apps/shared/logs/request.py``)
    now says a 503 happened on every tick, like any other 5xx — but *why* is a separate fact this
    line owns, and it is one an operator wants once per outage, not once per ten-second tick.

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

    ready_failed = [
        (e["event"], e["log_level"]) for e in logs if e["event"] == "health.ready_failed"
    ]
    assert ready_failed == [
        ("health.ready_failed", "error"),
        ("health.ready_failed", "warning"),
    ]
