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
    """Once per outage, not per probe; ``request.finished`` still states each 503."""
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
