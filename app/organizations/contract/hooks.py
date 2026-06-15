"""The ``org.created`` event — the organizations context's public hook.

Organizations owns and emits this event; other contexts subscribe to it without
importing one another. The only place that wires emitter to subscribers is the
composition root (:mod:`app.seeding`). Subscribers run inside the org-creating
transaction, so they seed their welcome data atomically with the new org.
"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

# (session, org_id, owner_user_id) -> None, run inside the creating transaction.
OrgCreatedHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]

_org_created_hooks: list[OrgCreatedHook] = []


def register_org_created(hook: OrgCreatedHook) -> None:
    _org_created_hooks.append(hook)


async def emit_org_created(
    session: AsyncSession, org_id: uuid.UUID, owner_user_id: uuid.UUID
) -> None:
    """Run every registered hook in the same transaction as the org creation.

    No-op when no hook is registered — e.g. callers that use the repository
    directly without going through the composition root (:mod:`app.seeding`).
    """
    for hook in _org_created_hooks:
        await hook(session, org_id, owner_user_id)
