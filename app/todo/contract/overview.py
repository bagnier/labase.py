"""The to-do context's dashboard overview.

Public surface consumed by the composition root (:mod:`app.overviews`). Org-scoped:
counts every task in the org, regardless of who created it.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.contract.overviews import Overview
from app.todo.infra.repository import TodoRepository

_RECENT = 3


async def overview(session: AsyncSession, org_id: uuid.UUID) -> Overview:
    items = await TodoRepository(session, org_id).all()
    open_items = [t for t in items if not t.done]
    done = len(items) - len(open_items)
    lines = [f"{len(open_items)} open", f"{done} done"] if items else ["No tasks yet"]
    return Overview(
        key="todo",
        title="To-do",
        icon="clipboard-text",
        href="todos",
        template="todo/_overview.html",
        data={"lines": lines, "recent": [t.title for t in open_items[:_RECENT]]},
    )
