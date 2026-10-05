"""Granting and revoking server admin, over auth's admin contract, which holds the last-admin
guard (the server twin of ``ensure_not_last_owner``).
"""

import uuid
from dataclasses import replace

from apps.auth.contract.admin import (
    LastAdminViolation as LastAdminViolation,
)
from apps.auth.contract.admin import (
    UserAdminStatus,
    ensure_not_last_admin,
    list_server_admins,
    set_server_admin,
)


class AdminNotFound(Exception):
    """No account exists for the given email."""

    def __init__(self, email: str) -> None:
        super().__init__(f"No account exists for {email}")
        self.email = email


def _sorted_admins(users: list[UserAdminStatus]) -> list[UserAdminStatus]:
    return sorted((u for u in users if u.is_admin), key=lambda u: u.email)


def _by_email(users: list[UserAdminStatus], email: str) -> UserAdminStatus | None:
    email = email.lower()
    return next((u for u in users if u.email.lower() == email), None)


async def list_admins() -> list[UserAdminStatus]:
    return _sorted_admins(await list_server_admins())


async def grant_admin(email: str) -> tuple[list[UserAdminStatus], bool, uuid.UUID]:
    """Promote ``email``; returns whether it changed (record a fact only then) and the id.
    Raises :class:`AdminNotFound`.

    GoTrue has no compare-and-set: a concurrent grant can still promote twice.
    """
    if not email:
        raise AdminNotFound(email)
    users = await list_server_admins()
    target = _by_email(users, email)
    if target is None:
        raise AdminNotFound(email)
    changed = not target.is_admin
    if changed:
        await set_server_admin(target.user_id, is_admin=True)
        users = [replace(u, is_admin=True) if u.user_id == target.user_id else u for u in users]
    return _sorted_admins(users), changed, target.user_id


async def set_admin(email: str, *, is_admin: bool) -> tuple[list[UserAdminStatus], bool, uuid.UUID]:
    """Grant or revoke admin; returns whether it changed (record a fact only then) and the id.
    Raises :class:`AdminNotFound` or :class:`LastAdminViolation`.

    The caller holds ``lock_last_admin_guard``: the count-then-act is atomic only under it.
    """
    users = await list_server_admins()
    target = _by_email(users, email)
    if target is None:
        raise AdminNotFound(email)
    admin_count = sum(1 for u in users if u.can_act)
    ensure_not_last_admin(
        removes_admin=not is_admin, target_is_admin=target.can_act, admin_count=admin_count
    )
    changed = target.is_admin != is_admin
    if changed:
        await set_server_admin(target.user_id, is_admin=is_admin)
        users = [replace(u, is_admin=is_admin) if u.user_id == target.user_id else u for u in users]
    return _sorted_admins(users), changed, target.user_id
