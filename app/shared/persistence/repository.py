import uuid
from typing import Any, ClassVar, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.persistence.base import Base


class BaseRepository[T: Base]:
    model: ClassVar[type[Any]]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pk: uuid.UUID) -> T | None:
        return cast(T | None, await self.session.get(self.model, pk))

    async def all(self) -> list[T]:
        return cast(list[T], list(await self.session.scalars(select(self.model))))

    async def save(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(self.model)) or 0


class OrgScopedRepository[T: Base](BaseRepository[T]):
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        super().__init__(session)
        self.org_id = org_id

    async def get(self, pk: uuid.UUID) -> T | None:
        return cast(
            T | None,
            await self.session.scalar(
                select(self.model).where(
                    self.model.id == pk,
                    self.model.org_id == self.org_id,
                )
            ),
        )

    async def all(self) -> list[T]:
        return cast(
            list[T],
            list(
                await self.session.scalars(
                    select(self.model).where(self.model.org_id == self.org_id)
                )
            ),
        )

    async def count(self) -> int:
        return (
            await self.session.scalar(
                select(func.count()).select_from(self.model).where(self.model.org_id == self.org_id)
            )
            or 0
        )
