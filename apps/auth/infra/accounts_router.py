"""Console screen: server accounts, through the GoTrue admin API (no app table). Deletion takes
the self-service path: ``UserDeleted`` and a soft delete.
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
from apps.auth.contract.settings import UsersSettings
from apps.auth.domain.admin_guard import LastAdminViolation, ensure_not_last_admin
from apps.auth.domain.models import AccountList
from apps.auth.infra.admin_guard import lock_last_admin_guard
from apps.auth.infra.user_repository import is_user_banned, list_server_admins
from apps.shared.dto import Message
from apps.shared.events.bus import events
from apps.shared.http import json_and_html, wants_full_page, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.supabase import get_admin_supabase
from apps.shared.settings.live import SettingsView

log = structlog.get_logger(__name__)

accounts_router = APIRouter(tags=["accounts"])

BAN_FOREVER = "876000h"  # ~100 years; GoTrue has no permanent ban flag
_PAGE_SIZE = 1000


def _ensure_enabled(users_settings: SettingsView) -> None:
    if not users_settings.user_management_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _list_accounts() -> list[dict[str, Any]]:
    """Live accounts, newest first."""
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
                    "disabled": is_user_banned(u),
                    "is_admin": u.app_metadata.get("role") == "admin",
                }
            )
        if len(users) < _PAGE_SIZE:
            break
        page += 1
    accounts.sort(key=lambda a: a["created_at"], reverse=True)
    return accounts


@accounts_router.get("", responses=json_and_html(AccountList))
async def list_accounts(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    users_settings: UsersSettings,
    q: str = "",
) -> Response:
    _ensure_enabled(users_settings)
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


async def _guard_last_admin(
    admin_session: AdminSession, current_user_id: uuid.UUID, user_id: str
) -> None:
    """Refuse to disable or delete the last admin who can act. Takes the last-admin lock (see
    ``admin_guard``), held until ``admin_session``'s transaction ends."""
    await lock_last_admin_guard(admin_session)
    admins = await list_server_admins()
    target_is_admin = any(u.user_id == uuid.UUID(user_id) and u.can_act for u in admins)
    try:
        ensure_not_last_admin(
            removes_admin=True,
            target_is_admin=target_is_admin,
            admin_count=sum(1 for u in admins if u.can_act),
        )
    except LastAdminViolation as exc:
        log.warning("settings.last_admin_violation", user_id=str(current_user_id), target=user_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


# The mutation is GoTrue's; the session is for the fact, which lands or fails with the request.
@accounts_router.post("/{user_id}/disable", responses=json_and_html(Message))
async def disable_user(
    request: Request,
    user_id: str,
    current_user: CurrentAdmin,
    admin_session: AdminSession,
    users_settings: UsersSettings,
) -> Response:
    _ensure_enabled(users_settings)
    _self_guard(current_user.id, user_id)
    await _guard_last_admin(admin_session, current_user.id, user_id)
    admin = get_admin_supabase().auth.admin
    await asyncio.to_thread(admin.update_user_by_id, user_id, {"ban_duration": BAN_FOREVER})
    await events.emit(
        AccountDisabled(user_id=current_user.id, entity_id=uuid.UUID(user_id)), admin_session
    )
    return _done(request, "Account disabled.")


@accounts_router.post("/{user_id}/enable", responses=json_and_html(Message))
async def enable_user(
    request: Request,
    user_id: str,
    current_user: CurrentAdmin,
    admin_session: AdminSession,
    users_settings: UsersSettings,
) -> Response:
    _ensure_enabled(users_settings)
    admin = get_admin_supabase().auth.admin
    await asyncio.to_thread(admin.update_user_by_id, user_id, {"ban_duration": "none"})
    await events.emit(
        AccountEnabled(user_id=current_user.id, entity_id=uuid.UUID(user_id)), admin_session
    )
    return _done(request, "Account enabled.")


@accounts_router.post("/{user_id}/delete", responses=json_and_html(Message))
async def delete_user(
    request: Request,
    user_id: str,
    current_user: CurrentAdmin,
    admin_session: AdminSession,
    users_settings: UsersSettings,
) -> Response:
    _ensure_enabled(users_settings)
    _self_guard(current_user.id, user_id)
    await _guard_last_admin(admin_session, current_user.id, user_id)
    await events.emit(
        AccountDeletedByAdmin(user_id=current_user.id, entity_id=uuid.UUID(user_id)), admin_session
    )
    # Same shape as the self-deletion's UserDeleted, which the cleanup consumers key on.
    await events.emit(
        UserDeleted(user_id=current_user.id, entity_id=uuid.UUID(user_id)), session=admin_session
    )
    await disable_account(user_id)
    await admin_session.commit()
    return _done(request, "Account deleted.")
