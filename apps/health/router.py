"""Liveness and readiness probes.

``/health/ready`` answers the one question an orchestrator asks on a timer: can this process
reach its database? Because it is polled — the container healthcheck every ten seconds — a
database it cannot reach is a *repeated* failure, so the probe puts it through the same verdict
as the background loops (:mod:`apps.shared.observability.loop`): the transition into degraded is
the bug the console has to show, the probes after it are the same outage still running.

Both paths are in ``RequestLogger``'s skip list — a probe every ten seconds would otherwise be
most of the timeline — which is precisely why the probe has to say this itself.
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.shared.observability.loop import LoopHealth
from apps.shared.persistence.database import _admin_engine

router = APIRouter(prefix="/health", tags=["health"])

log = structlog.get_logger(__name__)

# One per process, like the log sink's write outage: the state *is* "has this process been unable
# to reach its database", which is a property of the process and not of one probe.
_health = LoopHealth(log, "health.ready")


@router.get("/live")
async def liveness() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def readiness() -> JSONResponse:
    try:
        async with _admin_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        _health.tick_failed(exc)
        return JSONResponse({"status": "degraded"}, status_code=503)
    _health.tick_succeeded()
    return JSONResponse({"status": "ok"})
