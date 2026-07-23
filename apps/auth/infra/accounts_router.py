"""Console screen: server accounts (GoTrue-backed) — list, disable, enable, delete.

Accounts live in auth.users, so listing and state changes go through the GoTrue
admin API; there is no app table and no migration. Deletion follows the exact
self-serve path (``UserDeleted`` on the bus + soft delete) — one doctrine, two
entry points.
"""

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.auth.contract.deletion import disable_account
from apps.auth.contract.events import (
    AccountDeletedByAdmin,
    AccountDisabled,
    AccountEnabled,
    UserDeleted,
)
from apps.shared.events.bus import events
from apps.shared.http import wants_full_page, wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.supabase import get_admin_supabase
from apps.shared.settings import get_settings

log = structlog.get_logger("labase.auth.accounts")

accounts_router = APIRouter(tags=["accounts"])

BAN_FOREVER = "876000h"  # ~100 years; GoTrue has no permanent ban flag
_PAGE_SIZE = 1000


def _ensure_enabled() -> None:
    if not get_settings("users").user_management_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _list_accounts() -> list[dict[str, Any]]:
    """Every live GoTrue account (soft-deleted filtered out), newest first."""
    admin = get_admin_supabase().auth.admin
    accounts: list[dict[str, Any]] = []
    page = 1
    while True:
        users = admin.list_users(page=page, per_page=_PAGE_SIZE)
        for u in users:
            if getattr(u, "deleted_at", None):
                continue
            accounts.append(
                {
                    "id": str(u.id),
                    "email": u.email or "",
                    "created_at": u.created_at.strftime("%Y-%m-%d") if u.created_at else "",
                    "confirmed": u.email_confirmed_at is not None,
                    "disabled": _is_banned(u),
                    "is_admin": (u.app_metadata or {}).get("role") == "admin",
                }
            )
        if len(users) < _PAGE_SIZE:
            break
        page += 1
    accounts.sort(key=lambda a: a["created_at"], reverse=True)
    return accounts


def _is_banned(user: Any) -> bool:
    banned_until = getattr(user, "banned_until", None)
    return bool(banned_until)


@accounts_router.get("", response_model=None)
async def list_accounts(
    request: Request, current_user: CurrentAdmin, session: AdminSession, q: str = ""
) -> Response:
    _ensure_enabled()
    accounts = await asyncio.to_thread(_list_accounts)
    needle = q.strip().lower()
    if needle:
        accounts = [a for a in accounts if needle in a["email"].lower()]
    if wants_json(request):
        return JSONResponse({"accounts": accounts})
    context = {"accounts": accounts, "self_id": current_user.id, "q": q}
    if not wants_full_page(request):
        return templates.TemplateResponse(request, "_accounts.html", context)
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "user": current_user,
            **context,
            **await fullpage_context(session, current_user),
        },
    )


def _self_guard(current_user_id: uuid.UUID, user_id: str) -> None:
    if str(current_user_id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot act on your own account."
        )


def _done(request: Request, message: str) -> Response:
    if wants_json(request):
        return JSONResponse({"message": message})
    return RedirectResponse("/console/accounts", status_code=status.HTTP_303_SEE_OTHER)


@accounts_router.post("/{user_id}/disable", response_model=None)
async def disable_user(request: Request, user_id: str, current_user: CurrentAdmin) -> Response:
    _ensure_enabled()
    _self_guard(current_user.id, user_id)
    admin = get_admin_supabase().auth.admin
    await asyncio.to_thread(admin.update_user_by_id, user_id, {"ban_duration": BAN_FOREVER})
    await events.emit(AccountDisabled(actor_id=current_user.id, target_user_id=user_id))
    return _done(request, "Account disabled.")


@accounts_router.post("/{user_id}/enable", response_model=None)
async def enable_user(request: Request, user_id: str, current_user: CurrentAdmin) -> Response:
    _ensure_enabled()
    admin = get_admin_supabase().auth.admin
    await asyncio.to_thread(admin.update_user_by_id, user_id, {"ban_duration": "none"})
    await events.emit(AccountEnabled(actor_id=current_user.id, target_user_id=user_id))
    return _done(request, "Account enabled.")


@accounts_router.post("/{user_id}/delete", response_model=None)
async def delete_user(
    request: Request,
    user_id: str,
    current_user: CurrentAdmin,
    admin_session: AdminSession,
) -> Response:
    _ensure_enabled()
    _self_guard(current_user.id, user_id)
    await events.emit(AccountDeletedByAdmin(actor_id=current_user.id, target_user_id=user_id))
    await events.emit(
        UserDeleted(actor_id=current_user.id, entity_id=user_id), session=admin_session
    )
    await disable_account(user_id)
    await admin_session.commit()
    return _done(request, "Account deleted.")
