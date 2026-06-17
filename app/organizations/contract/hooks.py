"""The ``org.created`` event — the organizations context's public hook.

Organizations owns and emits this event; other contexts subscribe to it without
importing one another. The only place that wires emitter to subscribers is the
composition root (:mod:`app.seeding`). Subscribers run post-commit as background
tasks, so the org is guaranteed to exist in the DB when they execute.
"""

import uuid
from collections.abc import Awaitable, Callable

# (org_id, access_token) -> None, run post-commit as a background task.
OrgCreatedHook = Callable[[uuid.UUID, str], Awaitable[None]]

_org_created_hooks: list[OrgCreatedHook] = []


def register_org_created(hook: OrgCreatedHook) -> None:
    _org_created_hooks.append(hook)


async def emit_org_created(org_id: uuid.UUID, access_token: str) -> None:
    """Run every registered hook after the org-creating transaction has committed."""
    for hook in _org_created_hooks:
        await hook(org_id, access_token)
