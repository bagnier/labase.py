import uuid

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.todo.domain.models import TodoItem


class TodoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_org(self, org_id: uuid.UUID) -> list[TodoItem]:
        result = await self.session.execute(
            select(TodoItem).where(TodoItem.org_id == org_id).order_by(TodoItem.position)
        )
        return list(result.scalars().all())

    async def add(self, user_id: uuid.UUID, org_id: uuid.UUID, title: str) -> TodoItem:
        await self.session.execute(
            update(TodoItem).where(TodoItem.org_id == org_id).values(position=TodoItem.position + 1)
        )
        todo = TodoItem(user_id=user_id, org_id=org_id, title=title, position=0)
        self.session.add(todo)
        await self.session.flush()
        return todo

    async def get(self, todo_id: uuid.UUID, org_id: uuid.UUID) -> TodoItem | None:
        result = await self.session.execute(
            select(TodoItem).where(TodoItem.id == todo_id, TodoItem.org_id == org_id)
        )
        return result.scalars().first()

    async def set_done(self, todo: TodoItem, done: bool) -> TodoItem:
        todo.done = done
        self.session.add(todo)

        return todo

    async def set_title(self, todo: TodoItem, title: str) -> TodoItem:
        todo.title = title
        self.session.add(todo)

        return todo

    async def delete(self, todo: TodoItem) -> None:
        await self.session.delete(todo)

    @staticmethod
    def _reorder(
        items: list[TodoItem], todo_id: uuid.UUID, above_id: uuid.UUID | None
    ) -> list[TodoItem] | None:
        todo = next((t for t in items if t.id == todo_id), None)
        if todo is None:
            return None
        ordered = [t for t in items if t.id != todo_id]
        if above_id is None:
            ordered.append(todo)
        else:
            above_idx = next((i for i, t in enumerate(ordered) if t.id == above_id), None)
            if above_idx is None:
                return None
            ordered.insert(above_idx, todo)
        return ordered

    async def _apply_positions(self, org_id: uuid.UUID, ordered: list[TodoItem]) -> None:
        new_positions = {item.id: pos for pos, item in enumerate(ordered)}
        await self.session.execute(
            update(TodoItem)
            .where(TodoItem.org_id == org_id)
            .values(
                position=case(
                    *[(TodoItem.id == id_, pos) for id_, pos in new_positions.items()],
                    else_=TodoItem.position,
                )
            )
        )

    async def move_above(
        self, org_id: uuid.UUID, todo_id: uuid.UUID, above_id: uuid.UUID | None
    ) -> None:
        result = await self.session.execute(
            select(TodoItem).where(TodoItem.org_id == org_id).order_by(TodoItem.position)
        )
        items = list(result.scalars().all())
        ordered = self._reorder(items, todo_id, above_id)
        if ordered is None:
            return
        await self._apply_positions(org_id, ordered)
