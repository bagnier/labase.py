import uuid

from sqlalchemy import case, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.todo.domain.models import TodoItem


class TodoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[TodoItem]:
        result = await self.session.exec(
            select(TodoItem).where(TodoItem.user_id == user_id).order_by(col(TodoItem.position))
        )
        return list(result.all())

    async def add(self, user_id: uuid.UUID, title: str) -> TodoItem:
        await self.session.exec(  # type: ignore[call-overload]
            update(TodoItem)
            .where(col(TodoItem.user_id) == user_id)
            .values(position=col(TodoItem.position) + 1)
        )
        todo = TodoItem(user_id=user_id, title=title, position=0)
        self.session.add(todo)
        await self.session.commit()
        await self.session.refresh(todo)
        return todo

    async def get(self, todo_id: uuid.UUID, user_id: uuid.UUID) -> TodoItem | None:
        result = await self.session.exec(
            select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user_id)
        )
        return result.first()

    async def toggle_done(self, todo: TodoItem) -> TodoItem:
        todo.done = not todo.done
        self.session.add(todo)
        await self.session.commit()
        await self.session.refresh(todo)
        return todo

    async def set_title(self, todo: TodoItem, title: str) -> TodoItem:
        todo.title = title
        self.session.add(todo)
        await self.session.commit()
        await self.session.refresh(todo)
        return todo

    async def delete(self, todo: TodoItem) -> None:
        await self.session.delete(todo)
        await self.session.commit()

    async def move_above(
        self, user_id: uuid.UUID, todo_id: uuid.UUID, above_id: uuid.UUID | None
    ) -> None:
        result = await self.session.exec(
            select(TodoItem)
            .where(col(TodoItem.user_id) == user_id)
            .order_by(col(TodoItem.position))
        )
        items = list(result.all())
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
        await self.session.exec(  # type: ignore[call-overload]
            update(TodoItem)
            .where(col(TodoItem.user_id) == user_id)
            .values(
                position=case(
                    *[(col(TodoItem.id) == id_, pos) for id_, pos in new_positions.items()],
                    else_=col(TodoItem.position),
                )
            )
        )
        await self.session.commit()
