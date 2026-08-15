import asyncio
import uuid
from dataclasses import dataclass

import structlog

from apps.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger("labase.auth.directory")

_ADMIN_ROLE = "admin"
_PAGE_SIZE = 1000


@dataclass(frozen=True)
class UserAdminStatus:
    user_id: uuid.UUID
    email: str
    is_admin: bool


def _is_admin(app_metadata: dict | None) -> bool:
    return (app_metadata or {}).get("role") == _ADMIN_ROLE


async def _iter_all_users():
    """Every *live* auth user. Soft-deleted tombstones are skipped: they can't sign in, their
    email/identities are anonymized, and counting a soft-deleted admin would wrongly report the
    server as still having an owner (blocking the first-user bootstrap)."""
    admin = get_admin_supabase().auth.admin
    page = 1
    while True:
        users = await asyncio.to_thread(admin.list_users, page=page, per_page=_PAGE_SIZE)
        for u in users:
            if getattr(u, "deleted_at", None):
                continue
            yield u
        if len(users) < _PAGE_SIZE:
            return
        page += 1


async def list_server_admins() -> list[UserAdminStatus]:
    """Every auth user with their server-admin flag, read from ``app_metadata.role``."""
    return [
        UserAdminStatus(
            user_id=uuid.UUID(u.id),
            email=u.email or "",
            is_admin=_is_admin(u.app_metadata),
        )
        async for u in _iter_all_users()
    ]


async def count_server_admins() -> int:
    return sum(1 for u in await list_server_admins() if u.is_admin)


async def set_server_admin(user_id: uuid.UUID, *, is_admin: bool) -> None:
    """Set or clear the admin-only ``app_metadata.role`` claim. Effective on next sign-in."""
    admin = get_admin_supabase().auth.admin
    role = _ADMIN_ROLE if is_admin else None
    await asyncio.to_thread(admin.update_user_by_id, str(user_id), {"app_metadata": {"role": role}})


async def find_user_id_by_email(email: str) -> uuid.UUID | None:
    async for u in _iter_all_users():
        if u.email and u.email.lower() == email.lower():
            return uuid.UUID(u.id)
    return None


async def resolve_user_emails(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    admin = get_admin_supabase().auth.admin

    async def _get(uid: uuid.UUID) -> tuple[uuid.UUID, str]:
        # Best-effort, per id: the caller only wants a label. An id the directory no longer knows
        # (a deleted user, a stale id read off an old log line) resolves to "" — and so does a
        # record that cannot be read at all. The batch resolves ids concurrently, so *anything*
        # escaping here propagates out of the gather and fails the whole request: catching only
        # AuthApiError let a malformed GoTrue record (an identity missing a field the SDK's own
        # model declares required → a pydantic ValidationError) take down the Logs screen with a
        # 500. No failure to read one account is worth failing a page for; it is logged instead,
        # since a blank label would otherwise be the only trace.
        try:
            resp = await asyncio.to_thread(admin.get_user_by_id, str(uid))
        except Exception:
            log.warning("auth.user_lookup_failed", user_id=str(uid))
            return uid, ""
        email = resp.user.email if resp.user else ""
        return uid, email or ""

    results = await asyncio.gather(*(_get(uid) for uid in user_ids))
    return dict(results)
