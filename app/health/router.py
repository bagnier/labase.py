from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.shared.persistence.database import _admin_engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def readiness() -> JSONResponse:
    try:
        async with _admin_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "degraded", "detail": str(e)}, status_code=503)
