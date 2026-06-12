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
def _admin_engine():
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    return create_async_engine(url, echo=False, pool_pre_ping=True, connect_args=connect_args)


def _make_session_factory(engine_fn):
    @lru_cache
    def factory():
        return async_sessionmaker(engine_fn(), class_=AsyncSession, expire_on_commit=False)

    return factory


_user_session_factory = _make_session_factory(_user_engine)
_admin_session_factory = _make_session_factory(_admin_engine)


async def _session(factory) -> AsyncGenerator[AsyncSession]:
    # Frontière de transaction : commit après yield (succès uniquement — une exception
    # court-circuite le commit et l'async with rollback implicitement).
    # En contexte de test, une AsyncConnection partagée est injectée via l'override ;
    # session.commit() émet alors SAVEPOINT/RELEASE au lieu d'un vrai COMMIT.
    async with factory()() as session:
        yield session
        await session.commit()


async def get_user_session() -> AsyncGenerator[AsyncSession]:
    async for session in _session(_user_session_factory):
        yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession]:
    async for session in _session(_admin_session_factory):
        yield session
