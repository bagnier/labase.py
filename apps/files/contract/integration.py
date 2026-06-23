"""How the files context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the public
share router and the org-scoped router, claims the ``files`` slug, answers the dashboard
``OverviewQuery``, and drops a welcome file on ``OrgCreated``.
"""

import uuid

from fastapi import FastAPI

from apps.files.contract import settings
from apps.files.infra.repository import FileShareRepository, OrgFileRepository
from apps.files.infra.router import public_router, router
from apps.files.infra.storage import BUCKET, storage_path, user_storage_client
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import get_org_owner_id
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
    feature_switch,
    get_app_settings,
)
from apps.shared.host import Host, NavItem
from apps.shared.persistence.database import admin_session_factory

_RECENT = 3

_WELCOME_FILENAME = "welcome.txt"
_WELCOME_BODY = (
    b"Welcome to your organisation!\n\n"
    b"This is your shared file space. Upload documents here and share them with\n"
    b"your teammates via expiring links.\n"
)


# Mounts an org-scoped router under /{org_handle}; mounted last (see apps.main).


def mount(app: FastAPI, host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    _declare_settings()
    host.reserve("files")  # reserved even when disabled, to keep the slug from being squatted
    if not get_app_settings("files").enabled:
        return
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    app.include_router(public_router)
    app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Files", "folder", "files", "/files", order=30))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:g} {unit}"
        size /= 1024
    return f"{size:g} GB"


async def _overview(query: OverviewQuery) -> Overview:
    files = await OrgFileRepository(query.session, query.org_id).all()
    if files:
        total = sum(f.size_bytes for f in files)
        n = len(files)
        lines = [f"{n} file" + ("s" if n != 1 else ""), _human_size(total)]
    else:
        lines = ["No files yet"]
    return Overview(
        key="files",
        title="Files",
        icon="folder",
        href="files",
        template="files/_overview.html",
        data={"lines": lines, "recent": [f.filename for f in files[:_RECENT]]},
    )


def _declare_settings() -> None:
    settings.group = declare_app_settings(
        "files",
        defs=[
            feature_switch(),
            SettingDef("max_upload_mb", "number", "25", "Maximum upload size, in megabytes"),
            SettingDef("uploads_enabled", "boolean", "true", "Allow members to upload files"),
            SettingDef("welcome_message", "string", "Welcome aboard", "Shown on the files page"),
            SettingDef("signed_url_ttl", "number", "60", "Download link lifetime, in seconds"),
            SettingDef("share_link_ttl_days", "number", "7", "Share link lifetime, in days"),
            SettingDef(
                "org_storage_quota_mb",
                "number",
                "-1",
                "Storage quota per organisation, in megabytes (-1 = unlimited)",
            ),
        ],
        supabase=SupabaseLink(
            "Open the files bucket in Supabase Storage", f"storage/buckets/{BUCKET}"
        ),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    count, total = await FileShareRepository(query.session).count_and_size()
    if count:
        lines = [f"{count} file" + ("s" if count != 1 else ""), _human_size(total)]
    else:
        lines = ["No files yet"]
    return ConsoleOverview(key="files", title="Files", icon="folder", data={"lines": lines})


async def _seed(event: OrgCreated) -> None:
    async with admin_session_factory()() as session:
        owner_id = await get_org_owner_id(session, event.org_id)
    if owner_id is None:
        return

    file_id = uuid.uuid4()
    path = storage_path(event.org_id, file_id, _WELCOME_FILENAME)
    storage = user_storage_client(event.access_token)
    await storage.from_(BUCKET).upload(path, _WELCOME_BODY, {"content-type": "text/plain"})

    async with admin_session_factory()() as session:
        repo = OrgFileRepository(session, event.org_id)
        await repo.add(
            user_id=owner_id,
            filename=_WELCOME_FILENAME,
            storage_path=path,
            content_type="text/plain",
            size_bytes=len(_WELCOME_BODY),
        )
        await session.commit()
