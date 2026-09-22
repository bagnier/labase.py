"""Server-admin logic: the last-admin guard plus the small orchestrations the console runs on
top of auth's admin contract (look up by email, grant, revoke).

The guard is the server-scope twin of the organisations' last-owner guard
(``ensure_not_last_owner``).
"""

from apps.auth.contract.admin import (
    UserAdminStatus,
    find_user_id_by_email,
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


async def list_admins() -> list[UserAdminStatus]:
    """The server's admins, ordered by email."""
    users = await list_server_admins()
    return sorted((u for u in users if u.is_admin), key=lambda u: u.email)


async def grant_admin(email: str) -> tuple[list[UserAdminStatus], bool]:
    """Promote the account at ``email``; raises :class:`AdminNotFound` if none exists.

    Returns whether the account was newly granted — ``False`` for one already admin, which
    the caller must not journal as a fresh fact."""
    uid = await find_user_id_by_email(email) if email else None
    if uid is None:
        raise AdminNotFound(email)
    users = await list_server_admins()
    already_admin = any(u.user_id == uid and u.is_admin for u in users)
    if not already_admin:
        await set_server_admin(uid, is_admin=True)
    return await list_admins(), not already_admin


async def set_admin(email: str, *, is_admin: bool) -> tuple[list[UserAdminStatus], bool]:
    """Grant or revoke admin for ``email``, guarding the last-admin rule.

    Raises :class:`AdminNotFound` for an unknown email and :class:`LastAdminViolation` when the
    revoke would leave the server with no admin. Returns whether the status actually changed —
    ``False`` when ``email`` already held the requested status, which the caller must not
    journal as a fresh fact."""
    uid = await find_user_id_by_email(email)
    if uid is None:
        raise AdminNotFound(email)
    users = await list_server_admins()
    target_is_admin = any(u.user_id == uid and u.is_admin for u in users)
    admin_count = sum(1 for u in users if u.is_admin)
    ensure_not_last_admin(
        is_revoke=not is_admin, target_is_admin=target_is_admin, admin_count=admin_count
    )
    changed = target_is_admin != is_admin
    if changed:
        await set_server_admin(uid, is_admin=is_admin)
    return await list_admins(), changed
