from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import OperationalError


def test_liveness_returns_200(driver):
    response = driver.run(driver.client.get("/health/live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_when_db_ok(driver):
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("app.health.router._admin_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = mock_conn
        response = driver.run(driver.client.get("/health/ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_db_down(driver):
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = OperationalError("connect", {}, Exception("refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("app.health.router._admin_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = mock_conn
        response = driver.run(driver.client.get("/health/ready"))

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
