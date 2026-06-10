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
        await self.session.commit()
        return todo

    async def get(self, todo_id: uuid.UUID, org_id: uuid.UUID) -> TodoItem | None:
        result = await self.session.execute(
            select(TodoItem).where(TodoItem.id == todo_id, TodoItem.org_id == org_id)
        )
        return result.scalars().first()

    async def toggle_done(self, todo: TodoItem) -> TodoItem:
        todo.done = not todo.done
        self.session.add(todo)
        await self.session.commit()
        return todo

    async def set_title(self, todo: TodoItem, title: str) -> TodoItem:
        todo.title = title
        self.session.add(todo)
        await self.session.commit()
        return todo

    async def delete(self, todo: TodoItem) -> None:
        await self.session.delete(todo)
        await self.session.commit()

    async def move_above(
        self, org_id: uuid.UUID, todo_id: uuid.UUID, above_id: uuid.UUID | None
    ) -> None:
        result = await self.session.execute(
            select(TodoItem).where(TodoItem.org_id == org_id).order_by(TodoItem.position)
        )
        items = list(result.scalars().all())
        item_map = {t.id: t for t in items}
        if todo_id not in item_map:
            return
        ordered = [t for t in items if t.id != todo_id]
        if above_id is None:
            ordered.append(item_map[todo_id])
        else:
            if above_id not in item_map:
                return
            above_idx = next(i for i, t in enumerate(ordered) if t.id == above_id)
            ordered.insert(above_idx, item_map[todo_id])
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
        await self.session.commit()
