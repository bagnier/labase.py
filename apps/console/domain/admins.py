"""Server-admin logic: the last-admin guard plus the small orchestrations the console runs on
top of auth's admin contract (look up by email, grant, revoke).

The guard is the server-scope twin of the organisations' last-owner guard
(``ensure_not_last_owner``).
"""

import uuid
from dataclasses import replace

from apps.auth.contract.admin import (
    UserAdminStatus,
    list_server_admins,
    set_server_admin,
)


class LastAdminViolation(Exception):
    """Revoking would leave the server with no admin."""


class AdminNotFound(Exception):
    """No account exists for the given email."""

    def __init__(self, email: str) -> None:
        super().__init__(f"No account exists for {email}")
        self.email = email


def ensure_not_last_admin(*, is_revoke: bool, target_is_admin: bool, admin_count: int) -> None:
    if is_revoke and target_is_admin and admin_count <= 1:
        raise LastAdminViolation("The server must keep at least one admin")


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
    """
    users = await list_server_admins()
    target = _by_email(users, email)
    if target is None:
        raise AdminNotFound(email)
    admin_count = sum(1 for u in users if u.is_admin)
    ensure_not_last_admin(
        is_revoke=not is_admin, target_is_admin=target.is_admin, admin_count=admin_count
    )
    changed = target.is_admin != is_admin
    if changed:
        await set_server_admin(target.user_id, is_admin=is_admin)
        users = [replace(u, is_admin=is_admin) if u.user_id == target.user_id else u for u in users]
    return _sorted_admins(users), changed, target.user_id
