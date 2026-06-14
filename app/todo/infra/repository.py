import uuid

from sqlalchemy import case, select, update

from app.shared.persistence.repository import OrgScopedRepository
from app.todo.domain.models import TodoItem


class TodoRepository(OrgScopedRepository[TodoItem]):
    model = TodoItem

    async def all(self) -> list[TodoItem]:
        return list(
            await self.session.scalars(
                select(TodoItem).where(TodoItem.org_id == self.org_id).order_by(TodoItem.position)
            )
        )

    async def add(self, user_id: uuid.UUID, title: str) -> TodoItem:
        await self.session.execute(
            update(TodoItem)
            .where(TodoItem.org_id == self.org_id)
            .values(position=TodoItem.position + 1)
        )
        todo = TodoItem(user_id=user_id, org_id=self.org_id, title=title, position=0)
        return await self.save(todo)

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

    async def _apply_positions(self, ordered: list[TodoItem]) -> None:
        new_positions = {item.id: pos for pos, item in enumerate(ordered)}
        await self.session.execute(
            update(TodoItem)
            .where(TodoItem.org_id == self.org_id)
            .values(
                position=case(
                    *[(TodoItem.id == id_, pos) for id_, pos in new_positions.items()],
                    else_=TodoItem.position,
                )
            )
        )

    async def move_above(self, todo_id: uuid.UUID, above_id: uuid.UUID | None) -> None:
        items = await self.all()
        ordered = self._reorder(items, todo_id, above_id)
        if ordered is None:
            return
        await self._apply_positions(ordered)
