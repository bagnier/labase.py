import asyncio
import uuid
from dataclasses import dataclass

import structlog
from pydantic import ValidationError

from apps.shared.logs.dependency import is_refusal, log_dependency_failure
from apps.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger(__name__)

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
    try:
        await asyncio.to_thread(
            admin.update_user_by_id, str(user_id), {"app_metadata": {"role": role}}
        )
    except ValidationError:
        # The SDK parses the response after the server applied it — a non-2xx raises AuthApiError
        # before any parsing — so this can only mean the write landed and the returned record is
        # unreadable (an anonymized identity missing ``identity_data``). The action succeeded.
        log.info("set_server_admin.record_unreadable", user_id=str(user_id))


async def find_user_id_by_email(email: str) -> uuid.UUID | None:
    async for u in _iter_all_users():
        if u.email and u.email.lower() == email.lower():
            return uuid.UUID(u.id)
    return None


def _report_lookup_failures(failures: list[BaseException], total: int) -> None:
    """One verdict for the whole batch, never one per id.

    The lookups gather concurrently, so a directory that is down fails all of them at once: a line
    per id filed the same outage once per name on the screen, which on a busy timeline is sixty
    occurrences against one issue for a single page view. Reported once, with how many of how many
    failed — the shape a reader actually needs.

    The batch is as broken as its *worst* answer. A refusal (an account that is gone, a stale id
    off an old log line) is an ordinary outcome and must not speak for a batch that also hit a real
    outage, so the report is given the first failure that was not a refusal, and falls back to the
    refusal only when that is all there was.
    """
    if not failures:
        return
    worst = next((exc for exc in failures if not is_refusal(exc)), failures[0])
    log_dependency_failure(log, "auth.user_lookup_failed", worst, failed=len(failures), total=total)


async def resolve_user_emails(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    admin = get_admin_supabase().auth.admin
    failures: list[BaseException] = []

    async def _get(uid: uuid.UUID) -> tuple[uuid.UUID, str]:
        # Best-effort, per id: the caller only wants a label, so an id the directory no longer
        # knows resolves to "" — and so does a record that cannot be read at all. Catching every
        # exception, not just AuthApiError: the batch gathers concurrently, so anything escaping
        # here fails the whole page, and a GoTrue record the SDK's own model rejects is enough.
        # Kept, not logged: what it means is a property of the batch, judged once below.
        try:
            resp = await asyncio.to_thread(admin.get_user_by_id, str(uid))
        except Exception as exc:
            failures.append(exc)
            return uid, ""
        email = resp.user.email if resp.user else ""
        return uid, email or ""

    results = await asyncio.gather(*(_get(uid) for uid in user_ids))
    _report_lookup_failures(failures, len(user_ids))
    return dict(results)
