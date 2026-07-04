import uuid

from apps.shared.persistence.repository import OrgScopedRepository
from apps.todo.domain.models import TodoItem


class TodoRepository(OrgScopedRepository[TodoItem]):
    model = TodoItem
    default_order = TodoItem.position.asc()

    async def add(self, user_id: uuid.UUID, title: str) -> TodoItem:
        for item in await self.all():
            item.position += 1
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
        for pos, item in enumerate(ordered):
            item.position = pos
        await self.session.flush()

    async def move_above(self, todo_id: uuid.UUID, above_id: uuid.UUID | None) -> None:
        items = await self.all()
        ordered = self._reorder(items, todo_id, above_id)
        if ordered is None:
            return
        await self._apply_positions(ordered)
