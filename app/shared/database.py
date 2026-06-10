from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.shared.config import get_settings


@lru_cache
def _user_engine():
    settings = get_settings()
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    return create_async_engine(
        settings.database_url, echo=False, pool_pre_ping=True, connect_args=connect_args
    )


@lru_cache
def _service_engine():
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    return create_async_engine(url, echo=False, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def _user_session_factory():
    return async_sessionmaker(_user_engine(), class_=AsyncSession, expire_on_commit=False)


@lru_cache
def _service_session_factory():
    return async_sessionmaker(_service_engine(), class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _user_session_factory()() as session:
        yield session


async def get_service_session() -> AsyncGenerator[AsyncSession, None]:
    async with _service_session_factory()() as session:
        yield session
