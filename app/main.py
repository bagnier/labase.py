from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth.router import router as auth_router
from app.database import create_db_tables
from app.routers.dashboard import router as dashboard_router

BASE_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await create_db_tables()
    yield


app = FastAPI(title="labase", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(dashboard_router, tags=["dashboard"])
