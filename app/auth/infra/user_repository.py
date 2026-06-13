import asyncio
import uuid

from app.shared.persistence.supabase import get_admin_supabase


async def find_user_id_by_email(email: str) -> uuid.UUID | None:
    admin = get_admin_supabase().auth.admin
    page = 1
    while True:
        users = await asyncio.to_thread(admin.list_users, page=page, per_page=1000)
        for u in users:
            if u.email and u.email.lower() == email.lower():
                return uuid.UUID(u.id)
        if len(users) < 1000:
            return None
        page += 1


async def resolve_user_emails(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    admin = get_admin_supabase().auth.admin

    async def _get(uid: uuid.UUID) -> tuple[uuid.UUID, str]:
        resp = await asyncio.to_thread(admin.get_user_by_id, str(uid))
        email = resp.user.email if resp.user else ""
        return uid, email or ""

    results = await asyncio.gather(*(_get(uid) for uid in user_ids))
    return dict(results)
