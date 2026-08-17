"""Account deletion — the auth surface the profile Danger zone calls.

GoTrue is *soft*-deleted (sign-in impossible, row retained): hard-deleting
auth.users would block under open transactions holding key-share locks on the
user row, and would erase the record of the deletion with it. A purge job on the async
substrate can hard-delete cold soft-deleted accounts later.
"""

import asyncio
import functools

from apps.shared.persistence.supabase import get_admin_supabase


async def disable_account(user_id: str) -> None:
    supabase = get_admin_supabase()
    await asyncio.to_thread(
        functools.partial(supabase.auth.admin.delete_user, user_id, should_soft_delete=True)
    )
