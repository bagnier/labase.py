"""Liveness and readiness probes. ``/health/ready`` asks whether this process reaches its
database; it is polled, so a failure goes through the loop verdict
(AGENTS: a failure that repeats is one bug).
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.health.models import Probe
from apps.shared.logs.loop import LoopHealth
from apps.shared.persistence.database import _admin_engine

router = APIRouter(prefix="/health", tags=["health"])

log = structlog.get_logger(__name__)

# Per process: whether this process has been unable to reach its database.
_health = LoopHealth(log, "health.ready")


def readiness_failures() -> int:
    """Consecutive failed readiness probes on this instance, for the console tile."""
    return _health.failures


@router.get("/live", response_model=Probe)
async def liveness() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/ready", response_model=Probe)
async def readiness() -> JSONResponse:
    try:
        async with _admin_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        _health.tick_failed(exc)
        return JSONResponse({"status": "degraded"}, status_code=503)
    _health.tick_succeeded()
    return JSONResponse({"status": "ok"})
