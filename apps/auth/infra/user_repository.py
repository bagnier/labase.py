import asyncio
import uuid
from dataclasses import dataclass

from supabase_auth.errors import AuthApiError

from apps.shared.persistence.supabase import get_admin_supabase

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
    out: list[UserAdminStatus] = []
    async for u in _iter_all_users():
        out.append(
            UserAdminStatus(
                user_id=uuid.UUID(u.id),
                email=u.email or "",
                is_admin=_is_admin(u.app_metadata),
            )
        )
    return out


async def count_server_admins() -> int:
    return sum(1 for u in await list_server_admins() if u.is_admin)


async def set_server_admin(user_id: uuid.UUID, is_admin: bool) -> None:
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
        # Best-effort: an id the directory no longer knows (deleted user, a stale id captured in
        # an old log line) resolves to "" rather than failing the whole batch.
        try:
            resp = await asyncio.to_thread(admin.get_user_by_id, str(uid))
        except AuthApiError:
            return uid, ""
        email = resp.user.email if resp.user else ""
        return uid, email or ""

    results = await asyncio.gather(*(_get(uid) for uid in user_ids))
    return dict(results)
