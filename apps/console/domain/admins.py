"""Server-admin logic: the small orchestrations the console runs on top of auth's admin
contract (look up by email, grant, revoke) — the last-admin guard itself lives in
``apps.auth.contract.admin``, shared with every other path that can remove an admin.

The guard is the server-scope twin of the organisations' last-owner guard
(``ensure_not_last_owner``).
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
    """The server's admins, ordered by email."""
    return _sorted_admins(await list_server_admins())


async def grant_admin(email: str) -> tuple[list[UserAdminStatus], bool, uuid.UUID]:
    """Promote the account at ``email``; raises :class:`AdminNotFound` if none exists.

    Returns whether the account was newly granted (``False`` for one already admin, which the
    caller must not journal as a fresh fact) and its id, for the caller's own entity
    correlation — one directory scan serves the lookup, the guard and the listing alike, where
    the previous version made up to four.

    GoTrue's admin API has no compare-and-set: ``set_server_admin`` is a blind write, so a
    second grant racing between this read and that write can still re-promote and re-journal.
    Reading once instead of several times only narrows that window; it does not close it.
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
    """Grant or revoke admin for ``email``, guarding the last-admin rule.

    Raises :class:`AdminNotFound` for an unknown email and :class:`LastAdminViolation` when the
    revoke would leave the server with no admin. Returns whether the status actually changed
    (``False`` when ``email`` already held the requested status, which the caller must not
    journal as a fresh fact) and the account's id — one directory scan, as in :func:`grant_admin`.
    The caller must hold the last-admin guard's lock (``apps.auth.contract.admin
    .lock_last_admin_guard``) for the duration of this call — the read-then-act here is only
    atomic under that lock (issue #36).
    """
    users = await list_server_admins()
    target = _by_email(users, email)
    if target is None:
        raise AdminNotFound(email)
    admin_count = sum(1 for u in users if u.is_admin and not u.is_banned)
    ensure_not_last_admin(
        removes_admin=not is_admin,
        target_is_admin=target.is_admin and not target.is_banned,
        admin_count=admin_count,
    )
    changed = target.is_admin != is_admin
    if changed:
        await set_server_admin(target.user_id, is_admin=is_admin)
        users = [replace(u, is_admin=is_admin) if u.user_id == target.user_id else u for u in users]
    return _sorted_admins(users), changed, target.user_id
