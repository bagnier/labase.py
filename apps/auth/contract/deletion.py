"""Account deletion, called by the profile's danger zone.

A soft delete: a hard delete of ``auth.users`` blocks on transactions holding key-share locks on
the row, and erases the record of the deletion.
"""

import asyncio
import functools

from apps.shared.persistence.supabase import get_admin_supabase


async def disable_account(user_id: str) -> None:
    supabase = get_admin_supabase()
    await asyncio.to_thread(
        functools.partial(supabase.auth.admin.delete_user, user_id, should_soft_delete=True)
    )
