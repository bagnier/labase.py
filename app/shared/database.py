from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.shared.config import get_settings


@lru_cache
def _engine():
    settings = get_settings()
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    return create_async_engine(
        settings.database_url, echo=False, pool_pre_ping=True, connect_args=connect_args
    )


@lru_cache
def _session_factory():
    return async_sessionmaker(_engine(), class_=SQLModelAsyncSession, expire_on_commit=False)


async def create_db_tables() -> None:
    async with _engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[SQLModelAsyncSession, None]:  # type: ignore[misc]
    async with _session_factory()() as session:
        yield session
