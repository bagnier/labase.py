from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth.infra.router import router as auth_router
from app.profile.infra.router import router as profile_router
from app.todo.infra.router import router as todo_router
from app.shared.database import create_db_tables

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await create_db_tables()
    yield


app = FastAPI(title="labase", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(profile_router, tags=["profile"])
app.include_router(todo_router)
