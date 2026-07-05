import uuid
from operator import attrgetter
from typing import Any, ClassVar, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.persistence.base import Base, Positioned


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
    default_order: ClassVar[Any | None] = None

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
        query = select(self.model).where(self.model.org_id == self.org_id)
        if self.default_order is not None:
            query = query.order_by(self.default_order)
        return cast(list[T], list(await self.session.scalars(query)))

    async def count(self) -> int:
        return (
            await self.session.scalar(
                select(func.count()).select_from(self.model).where(self.model.org_id == self.org_id)
            )
            or 0
        )


class PositionedRepository[T: Base](OrgScopedRepository[T]):
    """Org-scoped rows kept in a dense, 0-based `position` order.

    `move_above` re-derives every position by load-then-mutate-then-flush so the
    optimistic lock (`version_id_col`) engages — never bulk `update()`, which
    would bypass it. `position_key` names the attribute callers identify rows
    by: the primary key by default, `page_id` for pages' nav items.
    """

    position_key: ClassVar[str] = "id"

    @classmethod
    def _reorder(cls, items: list[T], item_key: Any, above_key: Any | None) -> list[T] | None:
        """Pure reordering: `items` (position order) with `item_key` moved above
        `above_key`, or to the end when `above_key` is None. None if either key
        is unknown (concurrent deletion) — callers treat that as a no-op."""
        key = attrgetter(cls.position_key)
        item = next((i for i in items if key(i) == item_key), None)
        if item is None:
            return None
        ordered = [i for i in items if key(i) != item_key]
        if above_key is None:
            ordered.append(item)
        else:
            above_idx = next(
                (i for i, entry in enumerate(ordered) if key(entry) == above_key), None
            )
            if above_idx is None:
                return None
            ordered.insert(above_idx, item)
        return ordered

    async def move_above(self, item_key: Any, above_key: Any | None) -> None:
        ordered = self._reorder(await self.all(), item_key, above_key)
        if ordered is None:
            return
        for pos, entry in enumerate(ordered):
            cast(Positioned, entry).position = pos
        await self.session.flush()


async def count_all(session: AsyncSession, model: type[Any]) -> int:
    """Server-wide count for `model`, across every organisation (console overview)."""
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)
